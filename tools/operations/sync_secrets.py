#!/usr/bin/env python3
"""
===============================================================================
Multi-PC Cloud Migration & Secret / State Synchronization Utility
===============================================================================

Purpose:
    Manages cloud-native synchronization between developer workstations and
    Google Cloud Platform (Secret Manager & Cloud Storage). Enables zero-setup,
    multi-PC execution where any machine logged in via `gcloud auth login` can
    immediately run the Document Translator without local credential files.

Capabilities:
    - --check / --dry-run : Validates cloud secrets and GCS bucket connectivity
    - --push-secrets      : Provisions or updates Secret Manager secrets
    - --push-state        : Uploads model cache and default configs to GCS
    - --clean-local       : Safely purges temporary/local credential and state files

Usage Examples:
    # 1. Verify cloud connectivity & zero-credential readiness:
    python tools/operations/sync_secrets.py --check

    # 2. Push Gemini API key to Secret Manager:
    python tools/operations/sync_secrets.py --push-secrets --gemini-key "<YOUR_GEMINI_API_KEY>"

    # 3. Dry-run audit:
    python tools/operations/sync_secrets.py --dry-run
===============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.core.cloud_secrets import (
    get_default_project_id,
    get_gemini_api_key,
    get_langsmith_api_key,
    resolve_cloud_secret,
)
from backend.core.cloud_storage import (
    get_gcs_bucket_name,
    load_cloud_state,
    save_cloud_state,
)

SERVICE_NAME = "document-translator"


def run_gcloud_cmd(args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Runs a gcloud CLI command safely across Windows and POSIX."""
    is_win = sys.platform == "win32"
    cmd = ["gcloud"] + args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=is_win)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def create_or_update_secret(secret_id: str, secret_value: str, project_id: str, dry_run: bool = False) -> bool:
    """Creates a secret if not existing, or adds a new version in Google Cloud Secret Manager."""
    if dry_run:
        print(f"[DRY-RUN] Would create/update secret '{secret_id}' in project '{project_id}'")
        return True

    # Check if secret already exists
    code, _, _ = run_gcloud_cmd(["secrets", "describe", secret_id, f"--project={project_id}"])
    temp_path = os.path.join(tempfile.gettempdir(), f"sec_{secret_id}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(secret_value)

        if code != 0:
            print(f"Creating new secret '{secret_id}' in project '{project_id}'...")
            ret, out, err = run_gcloud_cmd([
                "secrets", "create", secret_id,
                f"--data-file={temp_path}",
                f"--project={project_id}",
            ])
        else:
            print(f"Adding new version to existing secret '{secret_id}' in project '{project_id}'...")
            ret, out, err = run_gcloud_cmd([
                "secrets", "versions", "add", secret_id,
                f"--data-file={temp_path}",
                f"--project={project_id}",
            ])

        if ret == 0:
            print(f"[SUCCESS] Secret '{secret_id}' configured successfully.")
            return True
        else:
            print(f"[ERROR] Failed to save secret '{secret_id}': {err}")
            return False
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def check_cloud_environment(project_id: str, dry_run: bool = False) -> bool:
    """
    Checks if Google Cloud Secret Manager and Google Cloud Storage are accessible
    and configured for zero-setup execution.
    """
    print("=" * 60)
    print(f"Checking Cloud-Native Environment for Project: {project_id}")
    print("=" * 60)

    bucket_name = get_gcs_bucket_name()
    print(f"Target GCS Bucket: gs://{bucket_name}")

    all_ok = True

    # 1. Check Gemini API Key
    print("\n[1/3] Checking Gemini API Key...")
    gemini_key = get_gemini_api_key(project_id=project_id)
    if gemini_key:
        masked = gemini_key[:8] + "..." + gemini_key[-4:] if len(gemini_key) > 12 else "***"
        print(f"  [OK] Gemini API key resolved from Secret Manager: {masked}")
    else:
        print("  [WARN] Gemini API key NOT found in Secret Manager or env.")
        all_ok = False

    # 2. Check LangSmith API Key (Optional)
    print("\n[2/3] Checking LangSmith Telemetry Key...")
    ls_key = get_langsmith_api_key(project_id=project_id)
    if ls_key:
        masked = ls_key[:8] + "..." + ls_key[-4:] if len(ls_key) > 12 else "***"
        print(f"  [OK] LangSmith API key resolved from Secret Manager: {masked}")
    else:
        print("  [INFO] LangSmith API key not configured (tracing disabled).")

    # 3. Check GCS State Files
    print(f"\n[3/3] Checking Cloud State in gs://{bucket_name}...")
    models = load_cloud_state(f"{SERVICE_NAME}/models_cache.json", default=None)
    if models and isinstance(models, list):
        print(f"  [OK] Models cache verified in GCS: {len(models)} models available.")
    else:
        print(f"  [WARN] Models cache not found at gs://{bucket_name}/{SERVICE_NAME}/models_cache.json")
        all_ok = False

    config = load_cloud_state(f"{SERVICE_NAME}/config.json", default=None)
    if config and isinstance(config, dict):
        print(f"  [OK] Default configuration verified in GCS: {config}")
    else:
        print(f"  [WARN] Configuration not found at gs://{bucket_name}/{SERVICE_NAME}/config.json")

    print("\n" + "=" * 60)
    if all_ok:
        print("[READY] All core cloud dependencies are healthy. Multi-PC portability confirmed!")
    else:
        print("[ACTION NEEDED] Some cloud dependencies are missing. Run with --push-secrets or --push-state.")
    print("=" * 60)
    return all_ok


def clean_local_workspace(dry_run: bool = False) -> None:
    """Removes local temporary and credential files from the workspace."""
    targets = [
        os.path.join(PROJECT_ROOT, "process_debug.txt"),
        os.path.join(PROJECT_ROOT, "import_error_log.txt"),
        os.path.join(PROJECT_ROOT, "backend_url.txt"),
        os.path.join(PROJECT_ROOT, "deploy", "backend_url.txt"),
        os.path.join(PROJECT_ROOT, "frontend", ".env.local"),
        os.path.join(PROJECT_ROOT, "backend", "desktop", "config.json"),
        os.path.join(PROJECT_ROOT, "backend", "storage", "models_cache.json"),
        os.path.join(PROJECT_ROOT, "models_cache.json"),
        os.path.join(PROJECT_ROOT, "config.json"),
        os.path.join(PROJECT_ROOT, "pytest.ini"),
    ]

    for t in targets:
        if os.path.exists(t):
            if dry_run:
                print(f"[DRY-RUN] Would remove: {t}")
            else:
                try:
                    os.remove(t)
                    print(f"Removed: {t}")
                except Exception as e:
                    print(f"Failed to remove {t}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-PC Cloud Migration & Secret / State Sync")
    parser.add_argument("--project", default=None, help="GCP Project ID (default: auto-detected)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without changes")
    parser.add_argument("--check", action="store_true", help="Verify cloud secrets and storage health")
    parser.add_argument("--push-secrets", action="store_true", help="Push local credentials to Secret Manager")
    parser.add_argument("--gemini-key", default=None, help="Gemini API Key to upload")
    parser.add_argument("--langsmith-key", default=None, help="LangSmith API Key to upload")
    parser.add_argument("--push-state", action="store_true", help="Push model cache and config to GCS")
    parser.add_argument("--clean-local", action="store_true", help="Remove local secret & temporary debug files")

    args = parser.parse_args()
    project_id = args.project or get_default_project_id()

    if args.clean_local:
        clean_local_workspace(dry_run=args.dry_run)

    if args.push_secrets:
        if args.gemini_key:
            create_or_update_secret("gemini-api-key", args.gemini_key, project_id, dry_run=args.dry_run)
        if args.langsmith_key:
            create_or_update_secret("langsmith-api-key", args.langsmith_key, project_id, dry_run=args.dry_run)

    if args.push_state:
        from backend.storage.model_storage import DEFAULT_MODELS
        print("Uploading models cache and configuration to GCS...")
        save_cloud_state(f"{SERVICE_NAME}/models_cache.json", DEFAULT_MODELS)
        save_cloud_state(f"{SERVICE_NAME}/config.json", {"provider": "Gemini 3.8 Flash", "target_lang": "Korean"})
        print("[SUCCESS] Cloud state synchronized.")

    if args.check or (not args.push_secrets and not args.push_state and not args.clean_local):
        check_cloud_environment(project_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
