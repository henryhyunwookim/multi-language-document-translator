#!/usr/bin/env python3
"""
===============================================================================
Offline Regression Corpus Evaluation Runner
===============================================================================

Purpose:
    Executes the versioned, offline evaluation test suite declared in
    tools/evaluation/corpus.v1.json. It verifies formatting invariants, office document
    fidelity, PDF gates, job idempotency, and multilingual constraints without
    invoking live cloud AI models or incurring API costs.

Usage Examples:
    # 1. Run the default offline evaluation suite:
    python tools/evaluation/run_evaluation.py

    # 2. Specify a custom corpus manifest or output destination:
    python tools/evaluation/run_evaluation.py --corpus tools/evaluation/corpus.v1.json --output output/evaluations/custom_report.json

Prerequisites & Dependencies:
    - Python 3.10+
    - PyMuPDF, python-docx, openpyxl, python-pptx, fastapi, httpx (test dependencies)

Inputs & Outputs:
    - Input:  tools/evaluation/corpus.v1.json (manifest of regression test suites)
    - Output: output/evaluation.json (structured test results summary)
===============================================================================
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import unittest

# =============================================================================
# Path Scaffolding & Root Detection
# =============================================================================
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# =============================================================================
# Main Evaluation Orchestrator
# =============================================================================
def main(argv: Optional[List[str]] = None) -> int:
    """Load the versioned evaluation corpus and execute all declared suites.

    Args:
        argv: Optional command-line argument list (defaults to sys.argv[1:]).

    Returns:
        0 if all offline checks passed successfully; 1 otherwise.
    """
    # Step 1: Configure CLI argument parser
    parser = argparse.ArgumentParser(
        description="Run the versioned offline corpus and write a machine-readable evaluation."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "tools" / "evaluation" / "corpus.v1.json",
        help="Path to the JSON corpus definition.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "evaluation.json",
        help="Destination path for the generated evaluation summary report.",
    )
    args = parser.parse_args(argv)

    # Step 2: Ingest and validate the corpus manifest
    if not args.corpus.exists():
        sys.stderr.write(f"Error: Corpus manifest not found at {args.corpus}\n")
        return 1

    corpus_data: Dict[str, Any] = json.loads(args.corpus.read_text(encoding="utf-8"))
    suite_names: List[str] = corpus_data.get("suites", [])
    if not suite_names:
        sys.stderr.write("Error: Corpus manifest contains no test suites.\n")
        return 1

    # Step 3: Discover and assemble unittest test suites
    suite = unittest.defaultTestLoader.loadTestsFromNames(suite_names)
    stream = io.StringIO()
    started = time.monotonic()

    # Step 4: Execute test suites capturing details in-memory
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    duration = round(time.monotonic() - started, 3)

    # Step 5: Synthesize structured machine-readable evaluation report
    report: Dict[str, Any] = {
        "corpus_version": corpus_data.get("version", 1),
        "passed": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "duration_seconds": duration,
        "failures": [
            {"test": case.id(), "detail": detail}
            for case, detail in result.failures + result.errors
        ],
        "skipped": [
            {"test": case.id(), "reason": reason}
            for case, reason in result.skipped
        ],
        "semantic_accuracy": "not_measured",
        "live_model_calls": False,
        "details": stream.getvalue(),
    }

    # Step 6: Atomic serialization to destination output path
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    status_str = "passed" if result.wasSuccessful() else "FAILED"
    print(f"{result.testsRun} offline checks: {status_str}. Report: {args.output}")

    return 0 if result.wasSuccessful() else 1


# =============================================================================
# CLI Entrypoint
# =============================================================================
if __name__ == "__main__":
    raise SystemExit(main())
