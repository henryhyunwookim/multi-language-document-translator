#!/usr/bin/env bash
# =============================================================================
# Multi-Language Document Translator - Frontend Cloud Run Deployment Script
# =============================================================================
# Usage:
#   ./deploy/deploy-frontend.sh [-b <backend_url>] [-p <gcp_project_id>] [-r <region>] [-s <service_name>] [-h]
#
# Flags:
#   -b : Backend API HTTPS URL (defaults to backend_url.txt or active service)
#   -p : Google Cloud Project ID (defaults to $GCP_PROJECT_ID or gcloud config)
#   -r : Google Cloud Region (defaults to $GCP_REGION or asia-northeast1)
#   -s : Cloud Run Service Name (defaults to translator-web)
#   -h : Display usage and help
# =============================================================================
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy-frontend.sh [OPTIONS]

Deploys the translator web frontend to Google Cloud Run.

Options:
  -b BACKEND_URL  Backend API URL (default: auto-discovered from backend_url.txt)
  -p PROJECT_ID   GCP Project ID (default: $GCP_PROJECT_ID or active gcloud config)
  -r REGION       GCP Region (default: $GCP_REGION or asia-northeast1)
  -s SERVICE      Service identifier (default: translator-web)
  -h              Show this help message and exit
EOF
  exit 0
}

# Determine directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"

# Default settings
BACKEND_URL=""
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE_NAME="translator-web"

while getopts "b:p:r:s:h" opt; do
  case "$opt" in
    b) BACKEND_URL="$OPTARG" ;;
    p) PROJECT_ID="$OPTARG" ;;
    r) REGION="$OPTARG" ;;
    s) SERVICE_NAME="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

# Fallback to positional argument for backward compatibility
if [ -z "$BACKEND_URL" ] && [ $# -gt 0 ]; then
  BACKEND_URL="$1"
fi

if [ -z "$PROJECT_ID" ]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
  echo "Error: GCP Project ID is unset. Run 'gcloud config set project <PROJECT_ID>' or pass -p <PROJECT_ID>." >&2
  exit 1
fi

# Resolve Backend URL
if [ -z "$BACKEND_URL" ]; then
    if [ -f "${SCRIPT_DIR}/backend_url.txt" ]; then
        BACKEND_URL=$(cat "${SCRIPT_DIR}/backend_url.txt")
    else
        echo "Querying active Cloud Run backend URL..."
        BACKEND_URL=$(gcloud run services describe translator-api --project "${PROJECT_ID}" --platform managed --region "${REGION}" --format 'value(status.url)' 2>/dev/null || true)
    fi
fi

if [ -z "$BACKEND_URL" ]; then
    echo "Error: Could not resolve backend URL." >&2
    echo "Usage: ./deploy/deploy-frontend.sh [-b <BACKEND_URL>]" >&2
    exit 1
fi

IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "=========================================="
echo "Deploying Frontend to Google Cloud Run"
echo "Project:     ${PROJECT_ID}"
echo "Service:     ${SERVICE_NAME}"
echo "Region:      ${REGION}"
echo "Backend API: ${BACKEND_URL}"
echo "=========================================="

cd "${FRONTEND_DIR}"

# Build and Push image using cloudbuild-frontend.yaml with NEXT_PUBLIC_API_URL baked in
echo "Building frontend container image with API URL: ${BACKEND_URL}..."
gcloud builds submit --project "${PROJECT_ID}" --config "${SCRIPT_DIR}/cloudbuild-frontend.yaml" \
  --substitutions="_NEXT_PUBLIC_API_URL=${BACKEND_URL},_IMAGE_TAG=${IMAGE_TAG}" .

# Deploy to Cloud Run
echo "Deploying ${SERVICE_NAME} to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_TAG}" \
  --project "${PROJECT_ID}" --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --port 8080

# Retrieve and print frontend URL
FRONTEND_URL=$(gcloud run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --platform managed --region "${REGION}" --format 'value(status.url)')
echo "=========================================="
echo "Frontend successfully deployed!"
echo "URL: ${FRONTEND_URL}"
echo "=========================================="
