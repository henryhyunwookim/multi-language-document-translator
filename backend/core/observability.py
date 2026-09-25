"""
Centralized Observability & Telemetry Module for Multi-Language Document Translator.
Integrates LangSmith distributed tracing, run evaluation, and performance monitoring.
"""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_LANGSMITH_INITIALIZED = False
_LANGSMITH_CLIENT: Any = None


def init_langsmith(langsmith_key: Optional[str] = None, project_name: str = "multi-language-document-translator") -> bool:
    """
    Initializes LangSmith environment variables and client connection.
    Guarantees only valid LangSmith keys are used, preventing collision
    with Gemini AI keys. Auto-resolves from Secret Manager if local environment is unset.
    Gracefully handles missing keys without throwing exceptions.
    """
    global _LANGSMITH_INITIALIZED, _LANGSMITH_CLIENT

    if any(os.environ.get(name, "").lower() == "false"
           for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")):
        return False

    if _LANGSMITH_INITIALIZED and _LANGSMITH_CLIENT is not None:
        return True

    key = langsmith_key if (langsmith_key and langsmith_key.startswith("ls")) else None

    if not key:
        env_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
        if env_key and env_key.startswith("ls"):
            key = env_key

    # Cloud Secret Manager fallback
    if not key:
        try:
            from backend.core.cloud_secrets import get_langsmith_api_key
            cloud_key = get_langsmith_api_key()
            if cloud_key and cloud_key.startswith("ls"):
                key = cloud_key
        except Exception as e:
            logger.debug(f"Cloud Secret Manager resolution for LangSmith key: {e}")

    if not key:
        logger.info("LangSmith API key not detected; tracing remains disabled.")
        return False

    os.environ["LANGSMITH_API_KEY"] = key
    os.environ["LANGCHAIN_API_KEY"] = key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project_name

    try:
        import langsmith
        _LANGSMITH_CLIENT = langsmith.Client(api_key=key)
        _LANGSMITH_INITIALIZED = True
        logger.info(f"LangSmith distributed tracing initialized successfully for project '{project_name}'.")
        return True
    except Exception as exc:
        logger.warning(f"Failed to initialize LangSmith client: {exc}")
        return False


def get_langsmith_client() -> Any:
    """Retrieves the active LangSmith client instance if initialized."""
    if not _LANGSMITH_INITIALIZED:
        init_langsmith()
    return _LANGSMITH_CLIENT


def _sanitize_inputs(inputs: Any) -> Any:
    """Strips massive raw binary image streams from LangSmith telemetry payloads."""
    if isinstance(inputs, dict):
        sanitized = {}
        for k, v in inputs.items():
            if k.lower() in ("api_key", "access_token", "authorization", "token"):
                sanitized[k] = "[redacted]"
            elif k == "image_bytes" and isinstance(v, (bytes, bytearray)):
                sanitized[k] = f"<image_bytes len={len(v)}>"
            elif isinstance(v, dict):
                sanitized[k] = _sanitize_inputs(v)
            elif isinstance(v, (bytes, bytearray)):
                sanitized[k] = f"<bytes len={len(v)}>"
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(inputs, (bytes, bytearray)):
        return f"<bytes len={len(inputs)}>"
    return inputs


def traceable_step(
    name: Optional[str] = None,
    run_type: str = "chain",
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Callable:
    """
    Decorator for wrapping functions as traced LangSmith spans.
    Automatically filters out heavy binary image buffers to ensure swift, lightweight telemetry.
    If LangSmith is active, generates full span telemetry.
    If LangSmith is unconfigured, executes directly without overhead.
    """
    def decorator(fn: Callable) -> Callable:
        step_name = name or fn.__name__

        try:
            from langsmith import traceable
            traced_fn = traceable(
                name=step_name,
                run_type=run_type,
                tags=tags,
                metadata=metadata,
                process_inputs=_sanitize_inputs,
            )(fn)

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if not _LANGSMITH_INITIALIZED:
                    init_langsmith()
                return traced_fn(*args, **kwargs)

            return wrapper
        except (ImportError, TypeError):
            @functools.wraps(fn)
            def pass_through(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            return pass_through

    return decorator
