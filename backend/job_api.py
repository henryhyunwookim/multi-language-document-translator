"""Authenticated batch submission, recovery, quality reports and artifacts."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from backend.jobs import JobManager, JobStore
from backend.quality.models import Finding, QualityReport
from backend.core.public_api_guard import check_public_request_limit, is_google_translate_provider

router = APIRouter(prefix="/jobs", tags=["durable jobs"])
_manager = None
_lock = threading.Lock()


def process_job(job, api_key, cancelled, store):
    from backend.api import _get_translator_modules, _process_file_with_translator
    _, GeminiTranslator, GoogleTransTranslator, _, _ = _get_translator_modules()
    options = job["options"]

    def log(event):
        if isinstance(event, dict):
            store.progress(job["id"], job["owner"], event.get("message", ""), event.get("progress"))
        else:
            store.progress(job["id"], job["owner"], str(event), 0)
        if not store.heartbeat(job["id"], job["owner"]):
            cancelled.set()

    common = dict(target_lang=options["target_lang"], log_callback=log, stop_event=cancelled)
    if is_google_translate_provider(options["provider"]):
        translator = GoogleTransTranslator(**common)
    else:
        translator = GeminiTranslator(api_key=api_key, model_name=options["provider"], **common)
    translator.glossary = options.get("glossary", {})
    translator.load_checkpoint = lambda: store.checkpoint(job["id"], job["owner"])
    translator.save_checkpoint = lambda value: store.checkpoint(job["id"], job["owner"], value)
    extension = Path(job["filename"]).suffix.lower()
    buffer = _process_file_with_translator(translator, job["input_path"], extension)
    try:
        report = translator.quality_report or QualityReport(findings=[Finding("unverified", "No quality report was produced by this adapter.")])
        return buffer.getvalue(), ".md" if extension in (".png", ".jpg", ".jpeg", ".webp") else extension, report.to_dict()
    finally:
        buffer.close()


def get_manager():
    global _manager
    with _lock:
        if _manager is None:
            directory = os.getenv("TRANSLATOR_JOB_DIR", str(Path(tempfile.gettempdir()) / "translator-jobs"))
            store = JobStore(directory, ttl=int(os.getenv("TRANSLATOR_JOB_TTL", "86400")))
            _manager = JobManager(store, process_job, workers=int(os.getenv("TRANSLATOR_JOB_WORKERS", "2")),
                                  per_provider=int(os.getenv("TRANSLATOR_PROVIDER_WORKERS", "2")))
            _manager.start()
    return _manager


def access(batch_id: str, authorization: str | None):
    token = authorization.removeprefix("Bearer ") if authorization and authorization.startswith("Bearer ") else ""
    manager = get_manager()
    try:
        manager.store.authorize(batch_id, token)
    except PermissionError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(410, str(exc)) from exc
    return manager


@router.post("/batches")
async def submit_batch(
    request: Request,
    files: list[UploadFile] = File(...), target_lang: str = Form(...), provider: str = Form(...),
    batch_id: str = Form(...), access_token: str = Form(...), api_key: str = Form(""), glossary: str = Form("{}"),
):
    check_public_request_limit(request, category="batch")
    if not 1 <= len(files) <= 20:
        raise HTTPException(400, "Select between 1 and 20 files per batch.")
    try:
        terms = json.loads(glossary)
        if not isinstance(terms, dict) or len(terms) > 200 or any(
                not isinstance(k, str) or not isinstance(v, str) or len(k) > 500 or len(v) > 500 for k, v in terms.items()):
            raise ValueError("Glossary must contain up to 200 source/target string pairs.")
        needs_key = not is_google_translate_provider(provider)
        if needs_key and not api_key.strip():
            raise ValueError("Enter your own Gemini API key, or choose Google Translate.")
        items = []
        total = 0
        for upload in files:
            raw = await upload.read(64 * 1024 * 1024 + 1)
            total += len(raw)
            if len(raw) > 64 * 1024 * 1024 or total > 256 * 1024 * 1024:
                raise ValueError("Batch limit: 64 MiB per file and 256 MiB total.")
            items.append((upload.filename or "document", raw))
        manager = get_manager()
        options = {"target_lang": target_lang, "provider": provider, "user_key": needs_key, "glossary": terms}
        await asyncio.to_thread(manager.store.submit, batch_id, access_token, items, options)
        if api_key.strip():
            manager.credentials[batch_id] = api_key.strip()
            with manager.store.connect() as db:
                db.execute("UPDATE jobs SET state='queued' WHERE batch_id=? AND state='waiting_credentials'", (batch_id,))
        return manager.store.snapshot(batch_id)
    except PermissionError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(410, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        for upload in files:
            await upload.close()


@router.get("/batches/{batch_id}")
async def batch_status(batch_id: str, authorization: str | None = Header(None)):
    return access(batch_id, authorization).store.snapshot(batch_id)


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(batch_id: str, authorization: str | None = Header(None)):
    manager = access(batch_id, authorization)
    manager.store.cancel(batch_id)
    return manager.store.snapshot(batch_id)


@router.post("/batches/{batch_id}/resume")
async def resume_batch(batch_id: str, api_key: str = Form(""), authorization: str | None = Header(None)):
    manager = access(batch_id, authorization)
    if api_key.strip():
        manager.credentials[batch_id] = api_key.strip()
        with manager.store.connect() as db:
            rows = db.execute("SELECT id,options FROM jobs WHERE batch_id=? AND state IN ('failed','cancelled','waiting_credentials')", (batch_id,)).fetchall()
            for row in rows:
                options = json.loads(row["options"])
                if not is_google_translate_provider(options["provider"]):
                    options["user_key"] = True
                    db.execute("UPDATE jobs SET options=? WHERE id=?", (json.dumps(options), row["id"]))
    manager.store.resume(batch_id)
    return manager.store.snapshot(batch_id)


@router.get("/batches/{batch_id}/{job_id}/artifact")
async def download_artifact(batch_id: str, job_id: str, authorization: str | None = Header(None)):
    manager = access(batch_id, authorization)
    try:
        job = manager.store.artifact(batch_id, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    filename = Path(job["filename"]).stem + "_translated" + Path(job["artifact"]).suffix
    return FileResponse(job["artifact"], filename=filename, headers={"Cache-Control": "no-store"})


@router.get("/batches/{batch_id}/{job_id}/report")
async def download_report(batch_id: str, job_id: str, authorization: str | None = Header(None)):
    manager = access(batch_id, authorization)
    jobs = manager.store.snapshot(batch_id, full_reports=True)["jobs"]
    job = next((job for job in jobs if job["id"] == job_id), None)
    if job is None or job["report"] is None:
        raise HTTPException(404, "Report is not ready.")
    from fastapi.responses import JSONResponse
    return JSONResponse(job["report"], headers={"Content-Disposition": f'attachment; filename="{job_id}_quality.json"', "Cache-Control": "no-store"})


def startup():
    get_manager()  # Recover queued and expired-lease work without a browser request.


def shutdown():
    global _manager
    if _manager:
        _manager.close()
        _manager = None


@router.get("/capabilities")
async def capabilities():
    from backend.quality.inspection import CAPABILITIES
    import shutil
    return {"formats": CAPABILITIES, "office_renderer_available": bool(os.getenv("OFFICE_RENDERER") or shutil.which("soffice") or shutil.which("libreoffice")),
            "job_ttl_seconds": get_manager().store.ttl, "max_files": 20}
