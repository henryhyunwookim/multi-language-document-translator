"""
===============================================================================
Backend Core Infrastructure Package
===============================================================================

Purpose:
    Exposes foundational utilities, shared logging configuration, and
    system primitives across the backend services and modules.
===============================================================================
"""

from __future__ import annotations

from backend.core.cloud_secrets import (
    get_default_project_id,
    get_gemini_api_key,
    get_langsmith_api_key,
    resolve_cloud_secret,
    resolve_oauth_credentials,
    resolve_oauth_token,
)
from backend.core.cloud_storage import (
    get_gcs_bucket_name,
    get_gcs_project_id,
    load_cloud_state,
    load_cloud_text,
    record_execution_run,
    save_cloud_state,
    save_cloud_text,
)
from backend.core.logger_config import (
    get_log_file_path,
    get_recent_logs,
    setup_logging,
)

__all__ = [
    "setup_logging",
    "get_log_file_path",
    "get_recent_logs",
    "resolve_cloud_secret",
    "get_gemini_api_key",
    "get_langsmith_api_key",
    "resolve_oauth_token",
    "resolve_oauth_credentials",
    "get_default_project_id",
    "load_cloud_state",
    "save_cloud_state",
    "load_cloud_text",
    "save_cloud_text",
    "record_execution_run",
    "get_gcs_bucket_name",
    "get_gcs_project_id",
]
