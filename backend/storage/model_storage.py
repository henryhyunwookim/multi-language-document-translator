"""
===============================================================================
Model Storage and Cloud-Native Cache Synchronization Module
===============================================================================

Purpose:
    Manages persistent storage, synchronization, and multi-tier retrieval for
    available translation models. Follows the Multi-PC Cloud Migration Blueprint:
      1. Fast In-Memory Cache (TTL governed, 60s)
      2. Google Cloud Storage Bucket (gs://<bucket>/document-translator/models_cache.json)
         as the canonical single source of truth across all machines.
      3. Safe local OS temporary directory cache (tempfile.gettempdir())
         guaranteeing zero workspace pollution.
      4. Hardcoded System Defaults (guarantees operational continuity)

Usage:
    from backend.storage.model_storage import load_models, save_models

    models = load_models()
    save_models(models)
===============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

try:
    from backend.core.cloud_storage import (
        get_gcs_bucket_name,
        load_cloud_state,
        save_cloud_state,
    )
except ImportError:
    from core.cloud_storage import (
        get_gcs_bucket_name,
        load_cloud_state,
        save_cloud_state,
    )

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS & CACHE LIFECYCLE CONFIGURATION
# =============================================================================

DEFAULT_MODELS: list[dict[str, str]] = [
    {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
    {"id": "gemini-3.8-pro", "name": "Gemini 3.8 Pro"},
    {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash"},
    {"id": "gemini-3.1-flash", "name": "Gemini 3.1 Flash"},
    {"id": "gemini-3.1-pro", "name": "Gemini 3.1 Pro"},
    {"id": "gemini-3.0-flash", "name": "Gemini 3.0 Flash"},
    {"id": "gemini-3.0-pro", "name": "Gemini 3.0 Pro"},
    {"id": "google-translate", "name": "Google Translate (Free)"},
]

# Cloud blob path
GCS_MODELS_BLOB: str = "document-translator/models_cache.json"

# Local cache strictly resides in OS temp dir to prevent workspace pollution
LOCAL_CACHE_PATH: str = os.path.join(tempfile.gettempdir(), "translator_models_cache.json")

# In-memory transient cache
_memory_cache: list[dict[str, str]] | None = None
_last_cache_time: float = 0.0
CACHE_TTL_SECONDS: float = 60.0


def get_bucket_name() -> str:
    """Returns the active GCS bucket name."""
    return get_gcs_bucket_name()


def load_models() -> list[dict[str, str]]:
    """
    Loads models list prioritizing:
      Step 1: In-memory transient cache (if within TTL window)
      Step 2: Google Cloud Storage bucket (canonical source of truth)
      Step 3: Local OS temporary directory cache (tempfile fallback)
      Step 4: Hardcoded DEFAULT_MODELS (absolute fallback)

    Returns:
        list[dict[str, str]]: Array of model definitions containing 'id' and 'name'.
    """
    global _memory_cache, _last_cache_time
    now = time.time()

    # Step 1: In-memory cache validation
    if _memory_cache and (now - _last_cache_time < CACHE_TTL_SECONDS):
        return _memory_cache

    # Step 2: Attempt remote GCS sync via cloud_storage
    try:
        data = load_cloud_state(GCS_MODELS_BLOB, default=None)
        if isinstance(data, list) and len(data) > 0:
            _memory_cache = data
            _last_cache_time = now
            # Mirror to temp cache
            try:
                with open(LOCAL_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
            return data
    except Exception as exc:
        logger.debug(f"Could not load models from GCS: {exc}")

    # Step 3: Local OS temp cache
    if os.path.exists(LOCAL_CACHE_PATH):
        try:
            with open(LOCAL_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    _memory_cache = data
                    _last_cache_time = now
                    return data
        except Exception:
            pass

    # Step 4: Hardcoded default models
    _memory_cache = DEFAULT_MODELS
    _last_cache_time = now
    return DEFAULT_MODELS


def save_models(models: list[dict[str, str]]) -> bool:
    """
    Persists models list permanently to Google Cloud Storage (canonical)
    and mirrors to local OS temp cache:
      Step 1: Validates and ensures default free engines are present
      Step 2: Updates in-memory transient cache
      Step 3: Mirrors to local OS temp cache
      Step 4: Uploads to Google Cloud Storage bucket

    Args:
        models (list[dict[str, str]]): List of model metadata dictionaries.

    Returns:
        bool: True if persistence succeeded in GCS or temp cache.
    """
    global _memory_cache, _last_cache_time
    if not models:
        return False

    # Step 1: Ensure baseline fallback engine is preserved
    has_gt = any(m.get("id") == "google-translate" for m in models)
    if not has_gt:
        models.append({"id": "google-translate", "name": "Google Translate (Free)"})

    # Step 2: Update in-memory state
    _memory_cache = models
    _last_cache_time = time.time()

    # Step 3: Save to OS temp cache
    try:
        with open(LOCAL_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(models, f, indent=2)
    except Exception as exc:
        logger.debug(f"Could not write to local temp cache {LOCAL_CACHE_PATH}: {exc}")

    # Step 4: Save to Google Cloud Storage
    try:
        success = save_cloud_state(GCS_MODELS_BLOB, models)
        if success:
            logger.info(f"Successfully persisted {len(models)} models to GCS '{GCS_MODELS_BLOB}'")
        return success
    except Exception as exc:
        logger.error(f"Failed to persist models to GCS: {exc}")
        return os.path.exists(LOCAL_CACHE_PATH)
