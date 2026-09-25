<#
.SYNOPSIS
    Builds and deploys the Multi-Language Document Translator backend to Google Cloud Run.

.DESCRIPTION
    Automates the backend container build using Google Cloud Build and provisions
    the translator-api service on Google Cloud Run. Retains the resulting service URL
    in deploy/backend_url.txt for frontend consumption.

.PARAMETER ProjectId
    The Google Cloud Platform project ID. If omitted, resolves from $env:GCP_PROJECT_ID
    or the active gcloud config.

.PARAMETER Region
    The GCP region for the Cloud Run deployment (defaults to asia-northeast1 or $env:GCP_REGION).

.PARAMETER ServiceName
    The target Cloud Run service name (defaults to translator-api).

.EXAMPLE
    .\deploy\deploy-backend.ps1

.EXAMPLE
    .\deploy\deploy-backend.ps1 -ProjectId "my-gcp-project" -Region "asia-northeast1"
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $false, HelpMessage = "Google Cloud Project ID")]
    [string]$ProjectId,

    [Parameter(Mandatory = $false, HelpMessage = "Google Cloud Region")]
    [string]$Region = "asia-northeast1",

    [Parameter(Mandatory = $false, HelpMessage = "Cloud Run service identifier")]
    [string]$ServiceName = "translator-api"
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Directory Scaffolding & Path Resolution
# =============================================================================
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
Set-Location $rootDir

# =============================================================================
# GCP Project ID Resolution
# =============================================================================
if (-not $ProjectId) {
    $ProjectId = $env:GCP_PROJECT_ID
    if (-not $ProjectId) {
        $ProjectId = (gcloud config get-value project 2>$null).Trim()
    }
}

if (-not $ProjectId -or $ProjectId -eq "(unset)") {
    Write-Error "GCP Project ID is unset. Run 'gcloud config set project <PROJECT_ID>' or pass -ProjectId parameter."
    exit 1
}

if ($env:GCP_REGION -and -not $PSBoundParameters.ContainsKey('Region')) {
    $Region = $env:GCP_REGION
}

$imageTag = "gcr.io/$ProjectId/$ServiceName"
$runtimeServiceAccount = "translator-runtime@$ProjectId.iam.gserviceaccount.com"

# =============================================================================
# Deployment Plan Display
# =============================================================================
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Deploying Backend to Google Cloud Run" -ForegroundColor Cyan
Write-Host "Project:  $ProjectId"
Write-Host "Service:  $ServiceName"
Write-Host "Region:   $Region"
Write-Host "Context:  $rootDir"
Write-Host "==========================================" -ForegroundColor Cyan

# Build and Push container image
Write-Host "Submitting Cloud Build for Backend: $imageTag..." -ForegroundColor Yellow
$cloudbuildConfig = Join-Path $scriptDir "cloudbuild-backend.yaml"
gcloud builds submit --project $ProjectId --config $cloudbuildConfig --substitutions=_IMAGE_TAG=$imageTag .
if ($LASTEXITCODE -ne 0) { throw 'Cloud Build failed; deployment stopped.' }

# Deploy to Cloud Run
Write-Host "Deploying $ServiceName to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --project $ProjectId `
    --image $imageTag `
    --platform managed `
    --region $Region `
    --allow-unauthenticated `
    --memory 2Gi `
    --timeout 1800 `
    --concurrency 8 `
    --max-instances 1 `
    --service-account $runtimeServiceAccount `
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$ProjectId,LANGSMITH_TRACING=false,LANGCHAIN_TRACING_V2=false"
if ($LASTEXITCODE -ne 0) { throw 'Cloud Run deployment failed.' }

# Retrieve and save backend URL
$backendUrl = (gcloud run services describe $ServiceName --project $ProjectId --platform managed --region $Region --format "value(status.url)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $backendUrl) { throw 'Could not retrieve deployed service URL.' }

Write-Host "==========================================" -ForegroundColor Green
Write-Host "Backend successfully deployed!" -ForegroundColor Green
Write-Host "URL: $backendUrl" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green

Set-Content -Path (Join-Path $scriptDir "backend_url.txt") -Value $backendUrl
