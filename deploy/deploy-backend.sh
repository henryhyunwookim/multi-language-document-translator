#!/usr/bin/env bash
# =============================================================================
# Multi-Language Document Translator - Backend Cloud Run Deployment Script
# =============================================================================
# Usage:
#   ./deploy/deploy-backend.sh [-p <gcp_project_id>] [-r <region>] [-s <service_name>] [-h]
#
# Flags:
#   -p : Google Cloud Project ID (defaults to $GCP_PROJECT_ID or gcloud config)
#   -r : Google Cloud Region (defaults to $GCP_REGION or asia-northeast1)
#   -s : Cloud Run Service Name (defaults to translator-api)
#   -h : Display usage and help
# =============================================================================
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy-backend.sh [OPTIONS]

Deploys the translator backend service to Google Cloud Run.

Options:
  -p PROJECT_ID  GCP Project ID (default: $GCP_PROJECT_ID or active gcloud config)
  -r REGION      GCP Region (default: $GCP_REGION or asia-northeast1)
  -s SERVICE     Service identifier (default: translator-api)
  -h             Show this help message and exit
EOF
  exit 0
}

# Default settings
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE_NAME="translator-api"

while getopts "p:r:s:h" opt; do
  case "$opt" in
    p) PROJECT_ID="$OPTARG" ;;
    r) REGION="$OPTARG" ;;
    s) SERVICE_NAME="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done

# Determine directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# Project Configuration
if [ -z "$PROJECT_ID" ]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
  echo "Error: GCP Project ID is unset. Run 'gcloud config set project <PROJECT_ID>' or pass -p <PROJECT_ID>." >&2
  exit 1
fi

IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
RUNTIME_SERVICE_ACCOUNT="translator-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=========================================="
echo "Deploying Backend to Google Cloud Run"
echo "Project:  ${PROJECT_ID}"
echo "Service:  ${SERVICE_NAME}"
echo "Region:   ${REGION}"
echo "Context:  ${ROOT_DIR}"
echo "=========================================="

# Build and Push backend container image
echo "Building container image: ${IMAGE_TAG}..."
gcloud builds submit --project "${PROJECT_ID}" --config "${SCRIPT_DIR}/cloudbuild-backend.yaml" --substitutions="_IMAGE_TAG=${IMAGE_TAG}" .

# Deploy to Cloud Run
echo "Deploying ${SERVICE_NAME} to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_TAG}" \
  --project "${PROJECT_ID}" --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 2Gi \
  --timeout 1800 \
  --concurrency 8 \
  --max-instances 1 \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},LANGSMITH_TRACING=false,LANGCHAIN_TRACING_V2=false"

# Retrieve and save backend URL
BACKEND_URL=$(gcloud run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --platform managed --region "${REGION}" --format 'value(status.url)')
echo "=========================================="
echo "Backend successfully deployed!"
echo "URL: ${BACKEND_URL}"
echo "=========================================="

echo "${BACKEND_URL}" > "${SCRIPT_DIR}/backend_url.txt"
