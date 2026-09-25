"""
===============================================================================
Desktop GUI Worker Process Wrapper Module
===============================================================================

Purpose:
    Provides a process-isolated worker execution wrapper for running document
    translations safely in a separate multiprocessing worker process.
    Communicates progress and completion events back to the CustomTkinter GUI
    event loop via multiprocessing Queues, preventing UI thread lockups.

Usage:
    import multiprocessing
    from backend.gui_wrapper import run_translation_process

    p = multiprocessing.Process(
        target=run_translation_process,
        args=(input_path, target_lang, provider, api_key, log_queue, result_queue)
    )
    p.start()

Outputs:
    - Pushes ("LOG", message) tuples to log_queue
    - Pushes ("SUCCESS", output_path) or ("ERROR", error_msg) to result_queue
===============================================================================
"""

from __future__ import annotations

import logging
import json
import uuid
import multiprocessing
import os
import sys
import traceback
from typing import Any, Optional

# Ensure current working directory and project root are discoverable
project_root = os.getcwd()
if project_root not in sys.path:
    sys.path.append(project_root)

# Resolve translator classes with fallback import
try:
    from backend.engines.translator import GeminiTranslator, GoogleTransTranslator
except ImportError:
    try:
        from backend.engines import GeminiTranslator, GoogleTransTranslator
    except ImportError:
        try:
            from backend.translator import GeminiTranslator, GoogleTransTranslator
        except ImportError:
            try:
                from translator import GeminiTranslator, GoogleTransTranslator
            except ImportError as exc:
                temp_err_log = os.path.join(tempfile.gettempdir(), "import_error_log.txt")
                try:
                    with open(temp_err_log, "w", encoding="utf-8") as f:
                        f.write(f"Import Error: {exc}\nPath: {sys.path}\n")
                except Exception:
                    pass
                raise

try:
    from backend.core.logger_config import setup_logging
except ImportError:
    try:
        from backend.core import setup_logging
    except ImportError:
        try:
            from backend.logger_config import setup_logging
        except ImportError:
            try:
                from logger_config import setup_logging
            except ImportError:
                setup_logging = lambda name: logging.getLogger(name)

logger = setup_logging("gui_wrapper")


# =============================================================================
# PROCESS ISOLATION & DEBUG LOGGING
# =============================================================================

def _debug_log(msg: str) -> None:
    """
    Writes thread-safe diagnosis logs to OS temp directory and standard logger.
    Guarantees no workspace pollution.
    """
    logger.debug(msg)
    try:
        temp_debug = os.path.join(tempfile.gettempdir(), "process_debug.txt")
        with open(temp_debug, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except OSError as err:
        logger.warning(f"Could not append to temp process_debug.txt: {err}")


# =============================================================================
# TRANSLATION WORKER PROCESS ENTRYPOINT
# =============================================================================

def run_translation_process(
    input_path: str,
    target_lang: str,
    provider_selection: str,
    api_key: str,
    log_queue: Optional[Any],
    result_queue: Any,
) -> None:
    """
    Process-safe worker entrypoint for document translation.

    Executes document translation in an isolated process to protect GUI responsiveness.
    Streams progress logs via `log_queue` and posts the final artifact status to `result_queue`.

    Args:
        input_path (str): Absolute or relative filesystem path to the input document.
        target_lang (str): Destination language for translation (e.g. 'English', 'Japanese').
        provider_selection (str): Chosen engine or model ID (e.g. 'gemini-3.1-pro', 'google-translate').
        api_key (str): Gemini API credentials key.
        log_queue (multiprocessing.Queue | None): Queue for UI streaming status logs.
        result_queue (multiprocessing.Queue): Queue for final ("SUCCESS", path) or ("ERROR", msg).
    """
    def log_callback(message: str) -> None:
        _debug_log(f"CB Log: {message}")
        if log_queue:
            try:
                log_queue.put(("LOG", message))
            except Exception as e:
                _debug_log(f"Failed to put message to log_queue: {e}")

    _debug_log(f"--- Process Started: {provider_selection} ---")
    _debug_log(f"Args: input={input_path}, lang={target_lang}")

    try:
        # Step 1: Initialize IPC queue communication
        if log_queue:
            log_queue.put(("LOG", f"Process started for {provider_selection}..."))
        _debug_log("Queue put successful.")

        # Step 2: Instantiate chosen translation engine
        _debug_log("Initializing Translator...")
        if "Google" in provider_selection or provider_selection == "google-translate":
            translator = GoogleTransTranslator(target_lang=target_lang, log_callback=log_callback)
        else:
            model_name = GeminiTranslator.clean_model_id(provider_selection)
            _debug_log(f"Creating GeminiTranslator with model: {model_name}")
            translator = GeminiTranslator(
                api_key=api_key,
                target_lang=target_lang,
                model_name=model_name,
                log_callback=log_callback,
            )
        _debug_log("Translator Initialized.")

        # Step 3: Identify format and process document
        _debug_log(f"Opening file: {input_path}")
        ext = os.path.splitext(input_path)[1].lower()

        from backend.engines.artifact_pipeline import process_file
        output_buffer = process_file(translator, input_path, ext)
        # Step 4: Persist output artifact
        project_root = os.getcwd()
        output_dir = os.path.join(project_root, "output")
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.basename(input_path)
        name, ext_found = os.path.splitext(base_name)

        out_ext = ".md" if ext in [".png", ".jpg", ".jpeg", ".webp"] else ext_found
        output_name = f"{name}_translated_{target_lang}_{uuid.uuid4().hex[:8]}{out_ext}"
        output_path = os.path.join(output_dir, output_name)

        _debug_log(f"Saving to {output_path}")
        with open(output_path, "wb") as f_out:
            f_out.write(output_buffer.getvalue())
        output_buffer.close()
        report_path = output_path + ".quality.json"
        from backend.quality.models import QualityReport, Finding
        report = translator.quality_report or QualityReport(findings=[Finding("unverified", "Adapter did not produce a quality report.")])
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump(report.to_dict(), report_file, ensure_ascii=False, indent=2)

        # Step 5: Post SUCCESS notification to UI
        _debug_log("Sending SUCCESS signal.")
        result_queue.put(("SUCCESS", output_path, report.status, report_path))
        _debug_log("Done.")

    except Exception as exc:
        _debug_log(f"CRITICAL EXCEPTION: {exc}\n{traceback.format_exc()}")
        result_queue.put(("ERROR", str(exc)))
        log_callback(f"Critical Error: {traceback.format_exc()}")
