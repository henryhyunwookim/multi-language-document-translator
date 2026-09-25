#!/usr/bin/env bash
# =============================================================================
# Multi-Language Document Translator - Full-Stack Cloud Run Deployment Script
# =============================================================================
# Usage:
#   ./deploy/deploy-all.sh [-p <gcp_project_id>] [-r <region>] [-h]
# =============================================================================
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy-all.sh [OPTIONS]

Orchestrates full-stack deployment of both backend and frontend to Google Cloud Run.

Options:
  -p PROJECT_ID  GCP Project ID (default: $GCP_PROJECT_ID or active gcloud config)
  -r REGION      GCP Region (default: $GCP_REGION or asia-northeast1)
  -h             Show this help message and exit
EOF
  exit 0
}

PROJECT_ARG=()
REGION_ARG=()

while getopts "p:r:h" opt; do
  case "$opt" in
    p) PROJECT_ARG=("-p" "$OPTARG") ;;
    r) REGION_ARG=("-r" "$OPTARG") ;;
    h) usage ;;
    *) usage ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "Starting Full-Stack Deployment"
echo "Step 1/2: Deploy Backend"
echo "=========================================="
"${SCRIPT_DIR}/deploy-backend.sh" "${PROJECT_ARG[@]}" "${REGION_ARG[@]}"

echo "=========================================="
echo "Step 2/2: Deploy Frontend"
echo "=========================================="
"${SCRIPT_DIR}/deploy-frontend.sh" "${PROJECT_ARG[@]}" "${REGION_ARG[@]}"

echo "=========================================="
echo "Full-Stack Deployment Complete!"
echo "=========================================="
