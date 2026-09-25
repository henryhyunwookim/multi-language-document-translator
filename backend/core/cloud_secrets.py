"""
===============================================================================
Cloud Secret & Credential Resolution Module (Google Cloud Secret Manager)
===============================================================================

Purpose:
    Provides universal, multi-PC portable secret resolution for API keys,
    OAuth tokens, and sensitive credentials using Google Cloud Secret Manager.

Resolution Strategy:
    1. Direct Environment Variable (e.g. GEMINI_API_KEY, LANGSMITH_API_KEY)
    2. Python google-cloud-secret-manager SDK (Application Default Credentials / Cloud Run Managed Identity)
    3. Authenticated gcloud CLI fallback: `gcloud secrets versions access latest`
       (ensures zero-setup immediate access on any developer PC with `gcloud auth login`)
    4. Optional local OS temporary cache (never pollutes git repository)

Usage:
    from backend.core.cloud_secrets import (
        resolve_cloud_secret,
        get_gemini_api_key,
        get_langsmith_api_key,
        resolve_oauth_token,
        resolve_oauth_credentials,
    )

    api_key = get_gemini_api_key()
===============================================================================
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory session cache for retrieved secrets to avoid repeated network hops
_SECRETS_CACHE: dict[str, str] = {}


def get_default_project_id() -> str:
    """
    Resolves the Google Cloud project ID from environment variables,
    active gcloud CLI configuration, or system defaults.
    """
    project_id = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("GCP_PROJECT")
    )
    if project_id and project_id.strip():
        return project_id.strip()

    # Attempt resolution via gcloud CLI config
    try:
        is_win = sys.platform == "win32"
        cmd = ["gcloud", "config", "get-value", "project"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            shell=is_win,
        )
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


def resolve_cloud_secret(secret_id: str, project_id: Optional[str] = None) -> Optional[str]:
    """
    Resolves a secret string from Google Cloud Secret Manager.
    Implements a dual-mode strategy: SDK with gcloud CLI fallback.

    Args:
        secret_id (str): The name/ID of the secret in Secret Manager.
        project_id (Optional[str]): GCP project ID. Inferred if omitted.

    Returns:
        Optional[str]: Secret value or None if resolution fails across all methods.
    """
    if not secret_id:
        return None

    target_project = project_id or get_default_project_id()
    if not target_project:
        return None

    # Check in-memory session cache first
    cache_key = f"{target_project}:{secret_id}"
    if cache_key in _SECRETS_CACHE:
        return _SECRETS_CACHE[cache_key]

    # Method 1: Google Cloud Secret Manager SDK
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
        # 3.0 second timeout to quickly fall back if ADC is expired/invalid
        response = client.access_secret_version(request={"name": name}, timeout=3.0, retry=None)
        secret_val = response.payload.data.decode("utf-8").strip()
        if secret_val:
            _SECRETS_CACHE[cache_key] = secret_val
            logger.debug(f"Resolved secret '{secret_id}' via Secret Manager SDK")
            return secret_val
    except Exception as exc:
        logger.debug(f"Secret Manager SDK resolution for '{secret_id}' skipped/failed: {exc}")

    # Method 2: gcloud CLI fallback (works on any developer PC logged in via gcloud auth login)
    try:
        is_win = sys.platform == "win32"
        cmd = [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret_id}",
            f"--project={target_project}",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            shell=is_win,
        )
        val = res.stdout.strip()
        if val:
            _SECRETS_CACHE[cache_key] = val
            logger.debug(f"Resolved secret '{secret_id}' via gcloud CLI fallback")
            return val
    except Exception as exc:
        logger.debug(f"gcloud CLI fallback for secret '{secret_id}' failed: {exc}")

    return None


def get_gemini_api_key(project_id: Optional[str] = None) -> Optional[str]:
    """
    Resolves the Gemini API key.
    Checks GEMINI_API_KEY environment variable first, then Secret Manager ('gemini-api-key').
    """
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    secret = resolve_cloud_secret("gemini-api-key", project_id=project_id)
    if secret:
        # Cache in environment variable for downstream libraries
        os.environ["GEMINI_API_KEY"] = secret
        return secret

    return None


def get_langsmith_api_key(project_id: Optional[str] = None) -> Optional[str]:
    """
    Resolves the LangSmith / LangChain telemetry API key.
    Checks environment variables first, then Secret Manager ('langsmith-api-key').
    """
    env_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if env_key and env_key.strip().startswith("ls"):
        return env_key.strip()

    secret = resolve_cloud_secret("langsmith-api-key", project_id=project_id)
    if secret and secret.strip().startswith("ls"):
        return secret.strip()

    return None


def resolve_oauth_token(
    secret_id: str = "document-translator-token",
    project_id: Optional[str] = None,
) -> Optional[str]:
    """
    Resolves serialized OAuth token JSON string from Secret Manager.
    """
    return resolve_cloud_secret(secret_id, project_id=project_id)


def resolve_oauth_credentials(
    secret_id: str = "document-translator-credentials",
    project_id: Optional[str] = None,
) -> Optional[str]:
    """
    Resolves OAuth Client Credentials JSON string from Secret Manager.
    """
    return resolve_cloud_secret(secret_id, project_id=project_id)
