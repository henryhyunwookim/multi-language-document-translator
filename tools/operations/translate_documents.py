#!/usr/bin/env python3
"""
===============================================================================
Inspected Document Translation Batch Processor
===============================================================================

Purpose:
    Executes high-fidelity, inspected document translations across multi-format
    files (PDF, DOCX, PPTX, XLSX) with durable checkpointing, quality verification,
    source-integrity validation, and atomic artifact replacement.

Usage Examples:
    # 1. Translate PDF to Korean and Excel to Japanese:
    python tools/operations/translate_documents.py \
        --model gemini-2.5-flash \
        --output-dir output/batch-runs/run1 \
        --job input/samples/document.pdf Korean \
        --job input/samples/workbook.xlsx Japanese

    # 2. Resume an interrupted translation batch:
    python tools/operations/translate_documents.py \
        --model gemini-2.5-flash \
        --output-dir output/batch-runs/run1 \
        --resume \
        --job input/samples/document.pdf Korean

Prerequisites:
    - Configured Google Cloud Gemini API key (via Secret Manager or GEMINI_API_KEY)
    - Python 3.10+ with backend dependencies installed

Inputs & Outputs:
    - Inputs:  Source documents (.pdf, .docx, .pptx, .xlsx, .txt, .png)
    - Outputs: Translated document artifacts, quality reports (.quality.json),
               execution metadata (.result.json), and atomic checkpoints.
===============================================================================
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Path Scaffolding & System Configuration
# =============================================================================
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# =============================================================================
# Atomic File System Utilities
# =============================================================================
def write_json(path: Path, value: Any) -> None:
    """Serialize data to JSON atomically using a sibling temporary file.

    Atomic writing ensures that interrupted processes or concurrent readers
    never encounter half-written or corrupt JSON files.

    Args:
        path: Target Path where the final JSON file should reside.
        value: Serializable Python dictionary or list.
    """
    temporary: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            suffix='.tmp',
            delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


# =============================================================================
# Main Batch Translation Runner
# =============================================================================
def main(argv: Optional[List[str]] = None) -> int:
    """Parse batch arguments and orchestrate concurrent translation jobs.

    Args:
        argv: Optional list of CLI arguments (defaults to sys.argv[1:]).

    Returns:
        0 if all jobs succeeded without fatal failure; 1 if any job failed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', action='append', nargs=2, metavar=('INPUT', 'LANGUAGE'), required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--review-model')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=range(1,5), default=2)
    parser.add_argument('--quality-workers', type=int, choices=range(1,5), default=2)
    parser.add_argument('--resume', action='store_true', help='Reuse compatible translation checkpoints.')
    parser.add_argument('--overwrite', action='store_true', help='Replace existing output artifacts.')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    # A local batch should not silently publish source documents to tracing.
    os.environ['LANGSMITH_TRACING'] = 'false'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    from backend.core.cloud_secrets import get_gemini_api_key
    from backend.core.model_client import create_model
    from backend.engines.translator import GeminiTranslator
    from backend.engines.artifact_pipeline import process_file
    args.output_dir.mkdir(parents=True, exist_ok=True)
    jobs, destinations = [], set()
    for filename, language in args.job:
        source = Path(filename).resolve(strict=True)
        if not source.is_file() or not language.strip():
            parser.error('Each job requires an existing file and nonempty language.')
        label = re.sub(r'[^\w-]+', '_', language).strip('_')
        suffix = source.suffix.lower()
        output_suffix = '.md' if suffix in ('.png','.jpg','.jpeg','.webp') else suffix
        output = args.output_dir / f'{source.stem[:90]}_{label}{output_suffix}'
        if output.resolve() == source or output.resolve() in destinations:
            parser.error('Output destinations must be distinct and must not overwrite inputs.')
        if output.exists() and not args.overwrite:
            parser.error(f'Output already exists: {output}; choose another directory or use --overwrite.')
        destinations.add(output.resolve())
        jobs.append((source, language, output))
    key = get_gemini_api_key()
    if not key:
        raise RuntimeError('The configured Gemini credential is unavailable.')

    def run(job):
        source, language, output = job
        checkpoint = output.with_name(output.name + '.checkpoint.json')
        result = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'language': language, 'model': args.model, 'output': str(output), 'status': 'failed'}
        translator = GeminiTranslator(api_key=key, target_lang=language, model_name=args.model,
                                      log_callback=lambda event: None)
        translator.quality_workers = args.quality_workers
        if args.review_model:
            translator.review_model = create_model(args.review_model, key)
            translator.review_model_name = args.review_model
        translator.load_checkpoint = lambda: json.loads(checkpoint.read_text(encoding='utf-8')) if args.resume and checkpoint.exists() else {}
        translator.save_checkpoint = lambda state: write_json(checkpoint, state)
        print(f'START {source.name} -> {language}', flush=True)
        try:
            artifact = process_file(translator, str(source), source.suffix)
            if hashlib.sha256(source.read_bytes()).hexdigest() != result['source_sha256']:
                raise RuntimeError('The source changed during translation.')
            report = translator.quality_report
            if report is None or report.finish().status == 'failed':
                raise RuntimeError('No releasable quality report was produced.')
            temporary = output.with_name(output.name + '.partial')
            temporary.write_bytes(artifact.getvalue())
            temporary.replace(output)
            result['status'] = report.status
        except Exception as exc:
            # Provider exceptions may contain credential-bearing request URLs.
            result['error_type'] = type(exc).__name__
        if translator.quality_report is not None:
            write_json(output.with_name(output.name + '.quality.json'), translator.quality_report.to_dict())
        write_json(output.with_name(output.name + '.result.json'), result)
        print(f'FINISH {output.name}: {result["status"]}', flush=True)
        return result
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(run, jobs))
    write_json(args.output_dir / 'results.json', results)
    return int(any(row['status'] == 'failed' for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
