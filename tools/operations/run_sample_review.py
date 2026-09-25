#!/usr/bin/env python3
"""
===============================================================================
Sample Review Translation Artifact Generator
===============================================================================

Purpose:
    Executes inspected Korean translation jobs against prepared excerpts
    in output/sample-reviews/sample-review with quality verification,
    reporting, and atomic checkpointing.

Usage:
    python tools/operations/run_sample_review.py
===============================================================================
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

ROOT_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "output" / "sample-reviews" / "sample-review",
    Path(__file__).resolve().parents[2] / "output" / "sample-review",
]
ROOT = next((p for p in ROOT_CANDIDATES if p.exists()), ROOT_CANDIDATES[0])


def main():
    from backend.core.cloud_secrets import get_gemini_api_key
    from google.ai.generativelanguage_v1beta import ModelServiceClient
    from google.api_core.client_options import ClientOptions
    from backend.engines.translator import GeminiTranslator
    from backend.engines.artifact_pipeline import process_file

    key = get_gemini_api_key()
    if not key:
        raise RuntimeError("Configured translation credential is unavailable.")
    client = ModelServiceClient(transport="rest", client_options=ClientOptions(api_key=key))
    available = [m.name.removeprefix("models/") for m in client.list_models(timeout=30)
                 if "generateContent" in m.supported_generation_methods]
    model = next((m for m in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash") if m in available), None)
    if not model:
        raise RuntimeError("No supported preferred model is available: " + ", ".join(available))
    print("Using available model:", model, flush=True)
    selections = json.loads((ROOT / "selection.json").read_text(encoding="utf-8"))

    def run(row):
        source = ROOT / row["sample"]
        output = ROOT / source.name.replace(".source-sample.", ".ko.")
        report_path = output.with_name(output.name + ".quality.json")
        checkpoint = output.with_name(output.name + ".checkpoint.json")
        result = {**row, "target_language": "Korean", "model": model, "output": output.name}
        if output.exists() and report_path.exists():
            return {**result, "status": json.loads(report_path.read_text(encoding="utf-8"))["status"]}
        start = time.monotonic()
        translator = GeminiTranslator(api_key=key, target_lang="Korean", model_name=model,
                                      log_callback=lambda event: None)
        if source.suffix in ('.pptx', '.xlsx'):
            from zipfile import ZipFile
            from lxml import etree
            import posixpath
            with ZipFile(source) as package:
                if source.suffix == '.pptx':
                    from backend.handlers.ooxml_text import _slide_parts
                    translator.sample_parts = set(_slide_parts(source.read_bytes()))
                else:
                    translator.sample_parts = {f'xl/worksheets/sheet{i}.xml' for i in row['sheet_positions']}
                    for part in list(translator.sample_parts):
                        relpath = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
                        if relpath in package.namelist():
                            for relation in etree.fromstring(package.read(relpath)):
                                if relation.get('Type', '').endswith('/drawing'):
                                    translator.sample_parts.add(posixpath.normpath(posixpath.join(posixpath.dirname(part), relation.get('Target'))).lstrip('/'))
            result['translated_parts'] = sorted(translator.sample_parts)
        translator.load_checkpoint = lambda: json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
        translator.save_checkpoint = lambda value: checkpoint.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        print("START", source.name, flush=True)
        try:
            artifact = process_file(translator, str(source), source.suffix)
            output.write_bytes(artifact.getvalue())
            result["status"] = translator.quality_report.status
        except Exception as exc:
            result["status"] = "failed"
            # Do not expose provider request URLs or credential-bearing exceptions.
            result["error_type"] = type(exc).__name__
        if translator.quality_report:
            report_path.write_text(json.dumps(translator.quality_report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        result["seconds"] = round(time.monotonic() - start, 1)
        (ROOT / (output.name + ".result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("READY", output.name, result["status"], flush=True)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(run, row) for row in selections]):
            results.append(future.result())
            (ROOT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Finished:", {state: sum(r['status'] == state for r in results) for state in ('passed', 'needs_review', 'failed')}, flush=True)


if __name__ == "__main__":
    main()
