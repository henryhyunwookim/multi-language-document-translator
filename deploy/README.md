# Deployment Guide

This directory consolidates all cloud deployment scripts, container configurations, and CI/CD pipelines for **Multi-Language Document Translator**.

---

## 🏛️ Architecture Overview

The system runs on **Google Cloud Run (Serverless Containers)**:

```
                      +-----------------------------+
                      |   Next.js Web Frontend      |
                      |   Service: translator-web   |
                      +--------------+--------------+
                                     |
                         HTTPS REST / SSE
                                     |
                                     v
                      +-----------------------------+
                      |   FastAPI Python Backend    |
                      |   Service: translator-api   |
                      +-----------------------------+
```

1. **Backend (`translator-api`)**: Python 3.11 container running FastAPI / Uvicorn, handling document parsing, Gemini multimodal translation, and output rendering.
2. **Frontend (`translator-web`)**: Node.js 20 container running Next.js, built with the backend URL embedded via `NEXT_PUBLIC_API_URL`.

---

## 📁 Directory Structure

```text
deploy/
├── README.md                 # Deployment documentation (this file)
├── cloudbuild.yaml           # Full-stack Cloud Build pipeline (Backend + Frontend)
├── cloudbuild-frontend.yaml  # Standalone Cloud Build configuration for Frontend
├── deploy-all.sh             # Bash full-stack orchestrator
├── deploy-all.ps1            # PowerShell full-stack orchestrator
├── deploy-backend.sh         # Bash backend deploy script
├── deploy-backend.ps1        # PowerShell backend deploy script
├── deploy-frontend.sh        # Bash frontend deploy script
├── deploy-frontend.ps1       # PowerShell frontend deploy script
└── backend_url.txt           # Generated file storing the latest backend URL (git-ignored)
```

---

## 🚀 Prerequisites

1. **Google Cloud SDK (`gcloud`)**:
   Ensure `gcloud` is installed and authenticated:
   ```bash
   gcloud auth login
   gcloud config set project <YOUR_GCP_PROJECT_ID>
   ```
2. **Required GCP Services**:
   Enable Cloud Run and Cloud Build on your project:
   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com
   ```

---

## 🛠️ Deployment Instructions

### Method 1: Full-Stack One-Click Deployment (Recommended)

#### Using Bash (macOS / Linux / Git Bash):
```bash
./deploy/deploy-all.sh
```

#### Using PowerShell (Windows):
```powershell
.\deploy\deploy-all.ps1
```

#### Using Cloud Build CI/CD:
```bash
gcloud builds submit --config deploy/cloudbuild.yaml .
```

---

### Method 2: Individual Service Deployment

#### 1. Backend Only
Deploys FastAPI to Cloud Run and records the service URL to `deploy/backend_url.txt`:
```bash
# Bash
./deploy/deploy-backend.sh

# PowerShell
.\deploy\deploy-backend.ps1
```

#### 2. Frontend Only
Reads the backend URL from `deploy/backend_url.txt` (or accepts it as an argument) and bakes it into the Next.js static bundle:
```bash
# Bash
./deploy/deploy-frontend.sh -b https://translator-api-xxxxx-uc.a.run.app

# PowerShell
.\deploy\deploy-frontend.ps1 -BackendUrl "https://translator-api-xxxxx-uc.a.run.app"
```

---

## ⚙️ Environment Variables & Overrides

The scripts automatically detect your active `gcloud` project and default to region `asia-northeast1`. You can override them using environment variables or the `-r` / `-Region` deployment option:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GCP_PROJECT_ID` | `$(gcloud config get-value project)` | Target GCP project ID |
| `GCP_REGION` | `asia-northeast1` | Target Cloud Run region |

## Runtime identity and deployment guarantees

Before the first deployment, run `./deploy/setup-runtime-identity.ps1 -ProjectId <project>` or `./deploy/setup-runtime-identity.sh <project>`. The helper creates `translator-runtime` if needed and grants object access on the translator bucket. The deployer needs `roles/iam.serviceAccountUser` on this identity.

Backend deployment uses this identity, 2 GiB memory, eight concurrent requests, a one-instance cap, and disabled LangSmith tracing. Public Gemini requests require the visitor's key. PowerShell scripts stop when a build or deployment fails, and cloud commands explicitly target the selected project.

Cloud Run's filesystem is ephemeral: SQLite jobs do not survive instance replacement. A Docker `VOLUME` declaration does not supply persistent storage. Move durable jobs to shared storage before increasing the instance count.

## Public service configuration

- Put translation and upload routes behind an external Application Load Balancer with Cloud Armor rate limits. Restrict Cloud Run ingress to that load balancer and disable the default `run.app` URL. The in-process limiter is a fallback, not distributed abuse control.
- Set and monitor instance, concurrency, request-timeout, and budget limits. Upload limits are 64 MiB per file and 256 MiB per batch.
- Keep the output bucket private, grant the runtime only bucket-scoped object access, and configure a short lifecycle rule for `document-translator/outputs/`. Verify job expiration and log retention before accepting confidential documents.
- After deploying, verify that `/logs`, `/logs/download`, `/cloud-links`, and `/cleanup/...` return 404 and that Gemini requests without a caller key are rejected.
- Publish data-handling terms appropriate to your deployment and provider settings; start with [Privacy and data handling](../docs/PRIVACY.md).
