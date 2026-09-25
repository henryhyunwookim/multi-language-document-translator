"""
===============================================================================
Document Translator FastAPI Backend Web Service
===============================================================================

Purpose:
    Exposes high-performance RESTful and Server-Sent Event (SSE) endpoints
    for multi-language document translation, pre-assessment, model discovery,
    and artifact retrieval. Designed for containerized deployment (e.g. Google
    Cloud Run, Docker) and web clients (e.g. Next.js).

Usage & CLI Invocation:
    # Run locally with live reload:
    uvicorn backend.api:app --host 0.0.0.0 --port 8080 --reload

    # Run in container / production:
    exec uvicorn backend.api:app --host 0.0.0.0 --port ${PORT:-8080}

Endpoints:
    - GET  /                        : Service status banner
    - GET  /health                  : Health probe check
    - GET  /models                  : List available AI translation models
    - POST /models                  : Refresh model cache using API key
    - POST /translate/text          : Synchronous text translation
    - POST /translate/document      : Synchronous binary document translation
    - POST /translate/document/stream : Real-time SSE streaming translation
    - GET  /download/{filename}     : Download translated output artifact
===============================================================================
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import io
import json
import logging
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional, Tuple

# Ensure project root and current dir are in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
for p in [project_root, current_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

import gc

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from backend.core.public_api_guard import (
    RequestBodyLimitMiddleware,
    check_public_request_limit,
    is_google_translate_provider,
)
try:
    from backend.engines.document_pipeline import assess_input_data
except ImportError:
    from backend.engines import assess_input_data

try:
    from backend.core.logger_config import setup_logging
except ImportError:
    try:
        from backend.core import setup_logging
    except ImportError:
        from logger_config import setup_logging

logger = setup_logging("translator_api")

# =============================================================================
# APPLICATION CONFIGURATION & MIDDLEWARE
# =============================================================================

logger.info("Initializing FastAPI app...")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Recover queued jobs on startup and stop workers when the server exits."""
    from backend.job_api import startup, shutdown

    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(
    title="Document Translator API",
    description="Universal Multi-Language Document Translation & Layout Reconstruction Service",
    version="2.0.0",
    lifespan=lifespan,
)

# Enable CORS for Next.js web application and local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # The UI uses capability tokens and form fields, not ambient cookies.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Filename", "X-Quality-Status", "X-Quality-Report"],
)
app.add_middleware(RequestBodyLimitMiddleware)

# Output directory configuration: default to OS temp directory to prevent workspace pollution
OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "translator_output"))
logger.info(f"Configured output directory: {OUTPUT_DIR}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

try:
    from backend.core.cloud_secrets import get_gemini_api_key
    from backend.core.cloud_storage import (
        get_ephemeral_output_bytes,
        record_execution_run,
        save_ephemeral_output_file,
    )
except ImportError:
    try:
        from core.cloud_secrets import get_gemini_api_key
        from core.cloud_storage import (
            get_ephemeral_output_bytes,
            record_execution_run,
            save_ephemeral_output_file,
        )
    except ImportError:
        def get_gemini_api_key(): return os.getenv("GEMINI_API_KEY")
        def record_execution_run(entry): pass
        def save_ephemeral_output_file(*args, **kwargs): return False, None
        def get_ephemeral_output_bytes(*args, **kwargs): return None


def _get_translator_modules() -> tuple[Any, Any, Any, Any, Any]:
    """
    Dynamically loads translator classes and model cache functions with fallback.
    """
    try:
        from backend.engines.translator import BaseTranslator, GeminiTranslator, GoogleTransTranslator
        from backend.storage.model_storage import load_models, save_models
    except ImportError:
        try:
            from backend.engines import BaseTranslator, GeminiTranslator, GoogleTransTranslator
            from backend.storage import load_models, save_models
        except ImportError:
            from translator import BaseTranslator, GeminiTranslator, GoogleTransTranslator
            from model_storage import load_models, save_models
    return BaseTranslator, GeminiTranslator, GoogleTransTranslator, load_models, save_models


# =============================================================================
# HEALTH & METADATA ENDPOINTS
# =============================================================================

@app.get("/")
async def root() -> dict[str, str]:
    """Root metadata endpoint verifying service health."""
    logger.info("Root endpoint hit")
    return {"status": "ok", "message": "Document Translator API is running"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for Cloud Run and Kubernetes ingress controllers."""
    return {"status": "healthy"}


def _resolve_request_gemini_key(user_key: Optional[str]) -> Optional[str]:
    """Use the caller's key; never spend the operator's key on public requests."""
    cleaned_key = (user_key or "").strip()
    if cleaned_key:
        return cleaned_key

    # Local operators can deliberately opt in for a private development run.
    # Cloud Run always ignores this fallback because its endpoint is public.
    local_opt_in = os.getenv("ALLOW_SERVER_GEMINI_KEY", "").lower() in {"1", "true", "yes"}
    if local_opt_in and not os.getenv("K_SERVICE"):
        return get_gemini_api_key() or None
    return None


def _require_gemini_key(provider: str, user_key: Optional[str]) -> Optional[str]:
    """Resolve a Gemini key and fail early when a caller omitted their key."""
    if is_google_translate_provider(provider):
        return None
    key = _resolve_request_gemini_key(user_key)
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Enter your own Gemini API key, or choose Google Translate.",
        )
    return key


# =============================================================================
# MODEL MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/models")
async def list_models() -> dict[str, list[dict[str, str]]]:
    """
    Returns the permanently stored list of available translation models.
    No API key required - accessible to all client users.
    """
    try:
        _, _, _, load_models, _ = _get_translator_modules()
        models = load_models()
        return {"models": models}
    except Exception as exc:
        logger.exception("Error loading models list")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/models")
async def update_models(request: Request, api_key: Optional[str] = Form(None)) -> dict[str, list[dict[str, str]]]:
    """
    Queries Gemini using the caller's key without changing shared model state.
    """
    try:
        check_public_request_limit(request, category="models")
        BaseTranslator, _, _, _, _ = _get_translator_modules()
        cleaned_key = _require_gemini_key("gemini", api_key)
        if not cleaned_key:
            raise HTTPException(status_code=400, detail="A Gemini API key is required to refresh models.")
        models = BaseTranslator.list_available_models(cleaned_key)
        return {"models": models}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error listing Gemini models")
        raise HTTPException(status_code=400, detail="Could not refresh the model list. Verify your key and try again.") from exc


# =============================================================================
# DOCUMENT TRANSLATION & PIPELINE PROCESSING
# =============================================================================

@app.post("/translate/text")
async def translate_text(
    request: Request,
    text: str = Form(...),
    target_lang: str = Form(...),
    provider: str = Form(...),
    api_key: Optional[str] = Form(None),
) -> dict[str, str]:
    """
    Translates raw text snippets synchronously.
    """
    try:
        check_public_request_limit(request)
        api_key = _require_gemini_key(provider, api_key)
        logger.info(f"Translating text with provider: {provider} to {target_lang}")
        _, GeminiTranslator, GoogleTransTranslator, _, _ = _get_translator_modules()

        if is_google_translate_provider(provider):
            translator = GoogleTransTranslator(target_lang=target_lang)
        else:
            model_name = GeminiTranslator.clean_model_id(provider)
            if not api_key:
                raise HTTPException(status_code=400, detail="API Key is required for Gemini models")
            translator = GeminiTranslator(api_key=api_key, target_lang=target_lang, model_name=model_name)

        result = translator.translate_text(text)
        return {"translated_text": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error during text translation")
        raise HTTPException(status_code=500, detail="Translation failed. Check the server log for details.") from exc


def _process_file_with_translator(translator: Any, temp_input_path: str, ext: str) -> io.BytesIO:
    from backend.engines.artifact_pipeline import process_file
    return process_file(translator, temp_input_path, ext)

def _quality_payload(translator):
    from backend.quality.models import QualityReport, Finding
    report = getattr(translator, "quality_report", None)
    if report is None:
        report = QualityReport(findings=[Finding("unverified", "This adapter did not produce a quality report.")])
    return report.to_dict()

@app.post("/translate/document")
async def translate_document(
    request: Request,
    file: UploadFile = File(...),
    target_lang: str = Form(...),
    provider: str = Form(...),
    api_key: Optional[str] = Form(None),
) -> Response:
    """
    Translates an uploaded document file synchronously and streams back the output binary.
    """
    temp_input_path: Optional[str] = None
    start_t = time.time()
    try:
        check_public_request_limit(request)
        api_key = _require_gemini_key(provider, api_key)
        logger.info(f"Translating document with provider: {provider}")
        _, GeminiTranslator, GoogleTransTranslator, _, _ = _get_translator_modules()

        temp_id = str(uuid.uuid4())
        ext = os.path.splitext(file.filename or "")[1].lower()
        temp_input_path = os.path.join(OUTPUT_DIR, f"temp_{temp_id}{ext}")

        with open(temp_input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        def log_cb(event: Any) -> None:
            if isinstance(event, dict):
                logger.info(f"[{event.get('stage', 'INFO')}] {event.get('message')}")
            else:
                logger.info(str(event))

        if is_google_translate_provider(provider):
            translator = GoogleTransTranslator(target_lang=target_lang, log_callback=log_cb)
        else:
            model_name = GeminiTranslator.clean_model_id(provider)
            if not api_key:
                raise HTTPException(status_code=400, detail="API Key is required for Gemini models")
            translator = GeminiTranslator(
                api_key=api_key,
                target_lang=target_lang,
                model_name=model_name,
                log_callback=log_cb,
            )

        output_buffer = _process_file_with_translator(translator, temp_input_path, ext)
        quality = _quality_payload(translator)

        name = os.path.splitext(file.filename or "document")[0]
        out_ext = ".md" if ext in [".png", ".jpg", ".jpeg", ".webp"] else ext
        name = os.path.basename(name.replace("\\", "/"))
        safe_language = "".join(c for c in target_lang if c.isalnum() or c in " -_") or "translated"
        output_filename = f"{name}_translated_{safe_language}_{temp_id}{out_ext}"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        raw_bytes = output_buffer.getvalue()
        with open(output_path, "wb") as f_out:
            f_out.write(raw_bytes)
        with open(output_path + ".quality.json", "w", encoding="utf-8") as report_file:
            json.dump(quality, report_file, ensure_ascii=False)

        # Upload to ephemeral GCS for transfer resilience
        content_type = "application/pdf" if out_ext == ".pdf" else "application/octet-stream"
        gcs_uploaded, signed_dl_url = save_ephemeral_output_file(output_filename, raw_bytes, content_type=content_type)

        record_execution_run({
            "action": "translate_document",
            "provider": provider,
            "target_lang": target_lang,
            "status": "success",
            "duration_seconds": round(time.time() - start_t, 2),
            "output_bytes": len(raw_bytes),
            "gcs_uploaded": gcs_uploaded,
        })

        encoded_filename = urllib.parse.quote(output_filename)

        # For files approaching Cloud Run 32MB HTTP limit, return JSON with direct download url
        if len(raw_bytes) > 28 * 1024 * 1024 and signed_dl_url:
            del raw_bytes
            output_buffer.close()
            del output_buffer
            gc.collect()
            return JSONResponse({
                "status": "success",
                "filename": output_filename,
                "download_url": signed_dl_url,
                "is_ephemeral": True,
                "quality_status": quality["status"],
                "quality_report_url": f"/download/{urllib.parse.quote(output_filename)}.quality.json",
            })

        headers = {
            "X-Quality-Status": quality["status"],
            "X-Quality-Report": f"/download/{urllib.parse.quote(output_filename)}.quality.json",
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Filename": encoded_filename,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Filename",
        }
        resp = Response(
            content=raw_bytes,
            media_type="application/octet-stream",
            headers=headers,
        )
        del raw_bytes
        output_buffer.close()
        del output_buffer
        gc.collect()
        return resp
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Document translation failed")
        record_execution_run({
            "action": "translate_document",
            "provider": provider,
            "target_lang": target_lang,
            "status": "failed",
        })
        raise HTTPException(status_code=500, detail="Document translation failed. Check the server log for details.") from exc
    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            try:
                os.remove(temp_input_path)
            except OSError as cleanup_err:
                logger.debug(f"Failed to remove temp input file: {cleanup_err}")


# =============================================================================
# REAL-TIME STREAMING (SERVER-SENT EVENTS)
# =============================================================================

@app.post("/translate/document/stream")
async def translate_document_stream(
    request: Request,
    file: UploadFile = File(...),
    target_lang: str = Form(...),
    provider: str = Form(...),
    api_key: Optional[str] = Form(None),
) -> StreamingResponse:
    """
    Streams translation events (SSE) in real-time.
    Provides live activity logs, dynamic progress, and keep-alive heartbeats to eliminate timeouts.
    """
    check_public_request_limit(request)
    cleaned_key = _require_gemini_key(provider, api_key)
    start_t = time.time()
    original_filename = os.path.basename((file.filename or "document").replace("\\", "/"))
    ext = os.path.splitext(original_filename)[1].lower()
    temp_id = str(uuid.uuid4())
    temp_input_path = os.path.join(OUTPUT_DIR, f"temp_{temp_id}{ext}")

    with open(temp_input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    event_queue: queue.Queue[Optional[dict[str, Any]]] = queue.Queue()

    def worker() -> None:
        try:
            _, GeminiTranslator, GoogleTransTranslator, _, _ = _get_translator_modules()

            def stream_log_callback(event: Any) -> None:
                if isinstance(event, dict):
                    event_queue.put({"type": "log", **event})
                else:
                    event_queue.put({
                        "type": "log",
                        "stage": "INFO",
                        "message": str(event),
                        "progress": None,
                        "timestamp": time.strftime("%H:%M:%S"),
                    })

            stream_log_callback({
                "stage": "INIT",
                "message": f"Received document: {original_filename} ({ext}). Target language: {target_lang}.",
                "progress": 5,
                "timestamp": time.strftime("%H:%M:%S"),
            })

            if is_google_translate_provider(provider):
                translator = GoogleTransTranslator(target_lang=target_lang, log_callback=stream_log_callback)
            else:
                model_name = GeminiTranslator.clean_model_id(provider)
                if not cleaned_key:
                    event_queue.put({"type": "error", "message": "API Key is required for Gemini models."})
                    return
                stream_log_callback({
                    "stage": "INIT",
                    "message": f"Configured Gemini AI model: {model_name}",
                    "progress": 8,
                    "timestamp": time.strftime("%H:%M:%S"),
                })
                translator = GeminiTranslator(
                    api_key=cleaned_key,
                    target_lang=target_lang,
                    model_name=model_name,
                    log_callback=stream_log_callback,
                )

            output_buffer = _process_file_with_translator(translator, temp_input_path, ext)
            quality = _quality_payload(translator)

            name = os.path.splitext(original_filename)[0]
            out_ext = ".md" if ext in [".png", ".jpg", ".jpeg", ".webp"] else ext
            safe_language = "".join(c for c in target_lang if c.isalnum() or c in " -_") or "translated"
            output_filename = f"{name}_translated_{safe_language}_{temp_id}{out_ext}"
            output_path = os.path.join(OUTPUT_DIR, output_filename)

            raw_bytes = output_buffer.getvalue()
            with open(output_path, "wb") as f_out:
                f_out.write(raw_bytes)
            with open(output_path + ".quality.json", "w", encoding="utf-8") as report_file:
                json.dump(quality, report_file, ensure_ascii=False)

            # Upload to ephemeral GCS for transfer resilience and direct high-speed download
            content_type = "application/pdf" if out_ext == ".pdf" else "application/octet-stream"
            gcs_uploaded, signed_dl_url = save_ephemeral_output_file(output_filename, raw_bytes, content_type=content_type)

            record_execution_run({
                "action": "translate_document_stream",
                "provider": provider,
                "target_lang": target_lang,
                "status": "success",
                "duration_seconds": round(time.time() - start_t, 2),
                "output_bytes": len(raw_bytes),
                "gcs_uploaded": gcs_uploaded,
            })

            # Bypasses Cloud Run 32MB HTTP limit if signed URL is present
            final_dl_url = signed_dl_url if signed_dl_url else f"/download/{urllib.parse.quote(output_filename)}"
            b64_content = base64.b64encode(raw_bytes).decode("utf-8") if len(raw_bytes) < 30 * 1024 * 1024 else None

            event_queue.put({
                "type": "complete",
                "filename": output_filename,
                "download_url": final_dl_url,
                "file_b64": b64_content,
                "progress": 100,
                "message": f"Artifact ready: {output_filename}. Quality status: {quality['status']}.",
                "quality_status": quality["status"],
                "quality_report_url": f"/download/{urllib.parse.quote(output_filename)}.quality.json",
                "is_ephemeral": True,
            })

            # Free memory immediately before worker thread ends
            del raw_bytes
            output_buffer.close()
            del output_buffer
            gc.collect()
        except Exception as exc:
            logger.exception("Error in stream worker")
            record_execution_run({
                "action": "translate_document_stream",
                "provider": provider,
                "target_lang": target_lang,
                "status": "failed",
            })
            event_queue.put({"type": "error", "message": "Translation failed. Check the server log for details."})
        finally:
            if os.path.exists(temp_input_path):
                try:
                    os.remove(temp_input_path)
                except OSError as cleanup_err:
                    logger.debug(f"Failed to remove temp input file: {cleanup_err}")
            event_queue.put(None)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                item = await asyncio.to_thread(event_queue.get, timeout=1.0)
            except queue.Empty:
                # Keep-alive heartbeat comment prevents proxy and Cloud Run timeouts
                yield ": keep-alive\n\n"
                continue

            if item is None:
                break

            yield f"data: {json.dumps(item)}\n\n"
            if item.get("type") in ["complete", "error"]:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# ARTIFACT DOWNLOAD & PERSISTENCE
# =============================================================================

@app.get("/download/{filename:path}")
async def download_file(filename: str) -> Response:
    """
    Serves translated output file artifacts from the configured output directory
    or ephemeral Google Cloud Storage fallback.
    """
    if os.path.basename(filename.replace("\\", "/")) != filename:
        raise HTTPException(status_code=404, detail="File not found or expired from ephemeral storage")
    output_root = os.path.realpath(OUTPUT_DIR)
    file_path = os.path.realpath(os.path.join(output_root, filename))
    if os.path.commonpath((output_root, file_path)) != output_root:
        raise HTTPException(status_code=404, detail="File not found or expired from ephemeral storage")
    if os.path.exists(file_path):
        encoded_filename = urllib.parse.quote(os.path.basename(file_path))
        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "Access-Control-Expose-Headers": "Content-Disposition, X-Filename",
            },
        )

    # Fallback to ephemeral GCS storage
    cloud_bytes = get_ephemeral_output_bytes(filename)
    if cloud_bytes is not None:
        encoded_filename = urllib.parse.quote(filename)
        return Response(
            content=cloud_bytes,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "X-Filename": encoded_filename,
                "Cache-Control": "no-store",
                "Access-Control-Expose-Headers": "Content-Disposition, X-Filename",
            },
        )

    raise HTTPException(status_code=404, detail="File not found or expired from ephemeral storage")


# =============================================================================
# SERVICE ENTRYPOINT
# =============================================================================

from backend.job_api import router as job_router
app.include_router(job_router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
