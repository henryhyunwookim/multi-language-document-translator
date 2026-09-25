#!/usr/bin/env bash
# Create a dedicated Cloud Run identity with access only to the translator bucket.
set -euo pipefail

PROJECT_ID="${1:-${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}}"
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "Pass a project ID or configure gcloud first." >&2
  exit 1
fi
BUCKET_NAME="${2:-${PROJECT_ID}-document-translator-data}"
ACCOUNT_ID="translator-runtime"
SERVICE_ACCOUNT="${ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$ACCOUNT_ID" \
    --project "$PROJECT_ID" \
    --display-name "Document Translator runtime"
fi

# The API needs object access for model cache, audit state, and temporary outputs.
# It is deliberately not granted Secret Manager access.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/storage.objectAdmin"

printf 'Runtime identity ready: %s\n' "$SERVICE_ACCOUNT"
printf 'Grant the deployer roles/iam.serviceAccountUser on this identity before deployment.\n'
