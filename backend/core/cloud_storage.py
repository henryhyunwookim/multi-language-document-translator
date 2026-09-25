"""
===============================================================================
Cloud Storage & State Persistence Module (Google Cloud Storage)
===============================================================================

Purpose:
    Provides cloud-native state persistence, memory storage, and operational
    log management for the Document Translator service.

Storage Model & Source of Truth:
    - Primary Canonical Storage: Google Cloud Storage (GCS)
      Bucket Pattern: gs://<project-id>-document-translator-data/<service>/<file>
    - Dual-Mode Resolution:
        1. Python google-cloud-storage SDK (managed identity / service accounts)
        2. Authenticated gcloud storage CLI fallback (for developer workstations)
    - Offline / Local Cache:
        Strictly isolated in OS temporary directory (tempfile.gettempdir()).
        Workspace root is NEVER polluted with cache or state JSON files.
    - Decoupled Operational Logs:
        Execution records, run history, and audit metadata are stored separately
        in GCS (run_log.json) and emitted as structured JSON to stdout.

Usage:
    from backend.core.cloud_storage import (
        load_cloud_state,
        save_cloud_state,
        load_cloud_text,
        save_cloud_text,
        record_execution_run,
        get_gcs_bucket_name,
    )
===============================================================================
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

SERVICE_NAME: str = "document-translator"


def get_gcs_project_id() -> str:
    """Resolves GCP Project ID for cloud storage operations."""
    pid = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("GCP_PROJECT")
    )
    if pid and pid.strip():
        return pid.strip()

    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "config", "get-value", "project"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=is_win)
        val = res.stdout.strip()
        if val and val != "(unset)":
            return val
    except Exception:
        pass

    # Attempt resolution via google.auth SDK (native Cloud Run environment)
    try:
        import google.auth
        _, auth_proj = google.auth.default()
        if auth_proj and auth_proj.strip():
            return auth_proj.strip()
    except Exception:
        pass

    # Attempt resolution via GCP Metadata Server
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            val = resp.read().decode("utf-8").strip()
            if val:
                return val
    except Exception:
        pass

    return ""


def get_gcs_bucket_name() -> str:
    """
    Resolves the canonical GCS bucket name.
    Priority:
      1. GCS_BUCKET_NAME / CONFIG_BUCKET / GCS_BUCKET environment variables
      2. <project-id>-document-translator-data
    """
    for env_var in ["GCS_BUCKET_NAME", "CONFIG_BUCKET", "GCS_BUCKET"]:
        val = os.getenv(env_var)
        if val and val.strip():
            return val.strip()

    project_id = get_gcs_project_id()
    if project_id:
        return f"{project_id}-document-translator-data"
    return ""


def _get_local_cache_path(blob_path: str) -> str:
    """
    Maps a GCS blob path to a safe, isolated OS temporary directory path.
    Prevents workspace pollution.
    """
    safe_name = blob_path.replace("/", "_").replace("\\", "_")
    temp_dir = os.path.join(tempfile.gettempdir(), "doc_translator_cloud_cache")
    try:
        os.makedirs(temp_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(temp_dir, safe_name)


def load_cloud_state(blob_path: str, default: Any = None) -> Any:
    """
    Loads JSON state from GCS with dual-mode fallback (SDK -> gcloud CLI -> OS temp cache).

    Args:
        blob_path (str): Relative blob path within bucket (e.g. 'document-translator/models_cache.json').
        default (Any): Default value if file not found or load fails.

    Returns:
        Any: Parsed JSON data or default.
    """
    bucket_name = get_gcs_bucket_name()
    local_cache = _get_local_cache_path(blob_path)

    # 1. Google Cloud Storage SDK
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if blob.exists(timeout=3.0):
            content = blob.download_as_text(encoding="utf-8", timeout=5.0)
            data = json.loads(content)
            # Update local OS temp cache
            try:
                with open(local_cache, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass
            return data
    except Exception as exc:
        logger.debug(f"GCS SDK load failed for '{bucket_name}/{blob_path}': {exc}")

    # 2. Authenticated gcloud storage CLI fallback
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cat", f"gs://{bucket_name}/{blob_path}"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=12, shell=is_win)
        data = json.loads(res.stdout)
        # Update local OS temp cache
        try:
            with open(local_cache, "w", encoding="utf-8") as f:
                f.write(res.stdout)
        except Exception:
            pass
        return data
    except Exception as exc:
        logger.debug(f"gcloud storage CLI load failed for 'gs://{bucket_name}/{blob_path}': {exc}")

    # 3. OS Temporary Directory Cache
    if os.path.exists(local_cache):
        try:
            with open(local_cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return default if default is not None else {}


def save_cloud_state(blob_path: str, data: Any) -> bool:
    """
    Saves JSON state to GCS as the single source of truth,
    mirroring to OS temporary cache (never local workspace).

    Args:
        blob_path (str): Relative blob path within bucket.
        data (Any): JSON-serializable python object.

    Returns:
        bool: True if written to GCS or temp cache, False otherwise.
    """
    bucket_name = get_gcs_bucket_name()
    local_cache = _get_local_cache_path(blob_path)
    data_str = json.dumps(data, ensure_ascii=False, indent=2)

    # Step 1: Write to OS temp cache
    try:
        with open(local_cache, "w", encoding="utf-8") as f:
            f.write(data_str)
    except Exception as exc:
        logger.warning(f"Could not write to local temp cache {local_cache}: {exc}")

    # Step 2: Upload to GCS via SDK
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(data_str, content_type="application/json", timeout=10.0)
        logger.info(f"Saved state to GCS: gs://{bucket_name}/{blob_path}")
        return True
    except Exception as exc:
        logger.debug(f"GCS SDK upload failed for '{bucket_name}/{blob_path}': {exc}")

    # Step 3: Upload via gcloud storage CLI fallback
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cp", local_cache, f"gs://{bucket_name}/{blob_path}"]
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
        logger.info(f"Saved state to GCS via gcloud CLI: gs://{bucket_name}/{blob_path}")
        return True
    except Exception as exc:
        logger.warning(f"Could not persist state to GCS '{bucket_name}/{blob_path}': {exc}")

    return os.path.exists(local_cache)


def load_cloud_text(blob_path: str, default: Optional[str] = None) -> Optional[str]:
    """Loads plain text content from GCS."""
    bucket_name = get_gcs_bucket_name()
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cat", f"gs://{bucket_name}/{blob_path}"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10, shell=is_win)
        return res.stdout
    except Exception:
        return default


def save_cloud_text(blob_path: str, content: str, content_type: str = "text/plain") -> bool:
    """Saves plain text content to GCS."""
    bucket_name = get_gcs_bucket_name()
    local_cache = _get_local_cache_path(blob_path)
    try:
        with open(local_cache, "w", encoding="utf-8") as f:
            f.write(content)
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cp", local_cache, f"gs://{bucket_name}/{blob_path}"]
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
        return True
    except Exception:
        return False


def record_execution_run(entry: dict[str, Any]) -> None:
    """
    Decoupled operational and execution logging.
    Appends structured execution metadata to GCS run_log.json
    and streams structured JSON to stdout for Cloud Logging.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entry_payload = {
        "timestamp": timestamp,
        "service": SERVICE_NAME,
        **entry,
    }

    # Stream structured log to stdout (Cloud Run automatically ingests into Cloud Logging)
    try:
        sys.stdout.write(f"[AUDIT_RUN] {json.dumps(entry_payload, ensure_ascii=False)}\n")
        sys.stdout.flush()
    except Exception:
        pass

    # Append to run_log.json in GCS
    log_blob_path = f"{SERVICE_NAME}/run_log.json"
    try:
        current_logs = load_cloud_state(log_blob_path, default=[])
        if not isinstance(current_logs, list):
            current_logs = []
        current_logs.append(entry_payload)
        # Cap to most recent 1000 execution runs to avoid unbounded growth
        if len(current_logs) > 1000:
            current_logs = current_logs[-1000:]
        save_cloud_state(log_blob_path, current_logs)
    except Exception as exc:
        logger.debug(f"Failed to append to GCS execution run log: {exc}")


EPHEMERAL_OUTPUTS_PREFIX = f"{SERVICE_NAME}/outputs"


def save_ephemeral_output_file(
    output_filename: str,
    raw_bytes: bytes,
    content_type: str = "application/octet-stream",
    expiration_minutes: int = 60,
) -> Tuple[bool, Optional[str]]:
    """
    Uploads a generated output file to GCS as a short-lived ephemeral object.
    Generates a signed download URL (valid for expiration_minutes) if available,
    allowing clients to download directly from GCS without passing through Cloud Run memory.

    Returns:
        Tuple[bool, Optional[str]]: (success, direct_download_url)
    """
    bucket_name = get_gcs_bucket_name()
    if not bucket_name:
        return False, None

    blob_path = f"{EPHEMERAL_OUTPUTS_PREFIX}/{output_filename}"
    signed_url: Optional[str] = None

    # 1. Google Cloud Storage SDK
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.metadata = {
            "temporary": "true",
            "created_at": str(time.time()),
            "service": SERVICE_NAME,
        }
        blob.upload_from_string(
            raw_bytes,
            content_type=content_type,
            timeout=30.0,
        )
        logger.info(f"Uploaded an ephemeral output to the configured GCS bucket ({len(raw_bytes)} bytes)")

        # Attempt to generate a v4 signed URL for direct browser download
        try:
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(minutes=expiration_minutes),
                method="GET",
                response_disposition=f'attachment; filename="{output_filename}"',
            )
            logger.info("Successfully generated GCS v4 signed download URL")
        except Exception as sign_err:
            logger.debug(f"Direct signed URL generation unavailable (using API route fallback): {sign_err}")

        return True, signed_url
    except Exception as exc:
        logger.warning(f"GCS SDK ephemeral upload failed: {exc}")

    # 2. Authenticated gcloud CLI fallback
    try:
        local_temp = os.path.join(tempfile.gettempdir(), f"ephem_{output_filename}")
        with open(local_temp, "wb") as f_tmp:
            f_tmp.write(raw_bytes)
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "cp", local_temp, f"gs://{bucket_name}/{blob_path}"]
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30, shell=is_win)
        try:
            os.remove(local_temp)
        except Exception:
            pass
        logger.info("Uploaded an ephemeral output to GCS via gcloud CLI")
        return True, None
    except Exception as cli_exc:
        logger.warning(f"gcloud CLI ephemeral upload failed: {cli_exc}")
        return False, None


def delete_ephemeral_output_file(output_filename: str) -> bool:
    """
    Explicitly deletes an ephemeral output file from GCS once downloaded by the client.
    Guarantees zero permanent cloud storage accumulation.
    """
    bucket_name = get_gcs_bucket_name()
    if not bucket_name:
        return False

    blob_path = f"{EPHEMERAL_OUTPUTS_PREFIX}/{output_filename}"
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if blob.exists(timeout=3.0):
            blob.delete(timeout=5.0)
            logger.info("Deleted an ephemeral output from GCS")
            return True
        return False
    except Exception as exc:
        logger.debug(f"GCS SDK delete failed for {blob_path}: {exc}")

    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "storage", "rm", f"gs://{bucket_name}/{blob_path}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=is_win)
        return res.returncode == 0
    except Exception:
        return False


def get_ephemeral_output_bytes(output_filename: str) -> Optional[bytes]:
    """
    Retrieves the raw bytes of an ephemeral output file from GCS if available.
    """
    bucket_name = get_gcs_bucket_name()
    if not bucket_name:
        return None
    blob_path = f"{EPHEMERAL_OUTPUTS_PREFIX}/{output_filename}"
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if blob.exists(timeout=3.0):
            return blob.download_as_bytes(timeout=30.0)
    except Exception as exc:
        logger.debug(f"GCS download failed for an ephemeral output: {exc}")
    return None

