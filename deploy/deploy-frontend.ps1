<#
.SYNOPSIS
    Builds and deploys the Next.js frontend of the Document Translator to Google Cloud Run.

.DESCRIPTION
    Bakes the Cloud Run backend API URL into the Next.js container build via Cloud Build
    substitutions and provisions the translator-web service on Google Cloud Run.

.PARAMETER BackendUrl
    The HTTPS URL of the deployed backend API. If omitted, automatically resolves
    from deploy/backend_url.txt or active Cloud Run service status.

.PARAMETER ProjectId
    The Google Cloud Platform project ID. If omitted, resolves from $env:GCP_PROJECT_ID
    or the active gcloud config.

.PARAMETER Region
    The GCP region for the Cloud Run deployment (defaults to asia-northeast1 or $env:GCP_REGION).

.PARAMETER ServiceName
    The target Cloud Run service name (defaults to translator-web).

.EXAMPLE
    .\deploy\deploy-frontend.ps1

.EXAMPLE
    .\deploy\deploy-frontend.ps1 -BackendUrl "https://translator-api-xyz.a.run.app" -ProjectId "my-gcp-project"
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $false, HelpMessage = "Backend API HTTPS URL")]
    [string]$BackendUrl,

    [Parameter(Mandatory = $false, HelpMessage = "Google Cloud Project ID")]
    [string]$ProjectId,

    [Parameter(Mandatory = $false, HelpMessage = "Google Cloud Region")]
    [string]$Region = "asia-northeast1",

    [Parameter(Mandatory = $false, HelpMessage = "Cloud Run frontend service identifier")]
    [string]$ServiceName = "translator-web"
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Directory Scaffolding & Path Resolution
# =============================================================================
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$frontendDir = Join-Path $rootDir "frontend"

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

# =============================================================================
# Resolve Backend API Endpoint
# =============================================================================
if (-not $BackendUrl) {
    $scriptBackendFile = Join-Path $scriptDir "backend_url.txt"
    if (Test-Path $scriptBackendFile) {
        $BackendUrl = (Get-Content $scriptBackendFile -Raw).Trim()
    } else {
        Write-Host "Querying active Cloud Run backend URL..." -ForegroundColor Yellow
        $BackendUrl = (gcloud run services describe translator-api --project $ProjectId --platform managed --region $Region --format "value(status.url)" 2>$null).Trim()
    }
}

if (-not $BackendUrl) {
    Write-Error "Could not resolve backend URL. Pass it as a parameter: .\deploy\deploy-frontend.ps1 -BackendUrl https://..."
    exit 1
}

$imageTag = "gcr.io/$ProjectId/$ServiceName"

# =============================================================================
# Deployment Plan Display
# =============================================================================
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Deploying Frontend to Google Cloud Run" -ForegroundColor Cyan
Write-Host "Project:     $ProjectId"
Write-Host "Service:     $ServiceName"
Write-Host "Region:      $Region"
Write-Host "Backend API: $BackendUrl"
Write-Host "==========================================" -ForegroundColor Cyan

Set-Location $frontendDir

# Build frontend container using Cloud Build with NEXT_PUBLIC_API_URL baked in
Write-Host "Submitting Cloud Build for Frontend..." -ForegroundColor Yellow
$cloudbuildConfig = Join-Path $scriptDir "cloudbuild-frontend.yaml"
gcloud builds submit --project $ProjectId --config $cloudbuildConfig --substitutions="_NEXT_PUBLIC_API_URL=$BackendUrl,_IMAGE_TAG=$imageTag" .
if ($LASTEXITCODE -ne 0) { throw 'Cloud Build failed; deployment stopped.' }

# Deploy to Cloud Run
Write-Host "Deploying $ServiceName to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --project $ProjectId `
    --image $imageTag `
    --platform managed `
    --region $Region `
    --allow-unauthenticated `
    --port 8080
if ($LASTEXITCODE -ne 0) { throw 'Cloud Run deployment failed.' }

# Retrieve and print frontend URL
$frontendUrl = (gcloud run services describe $ServiceName --project $ProjectId --platform managed --region $Region --format "value(status.url)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $frontendUrl) { throw 'Could not retrieve deployed service URL.' }

Write-Host "==========================================" -ForegroundColor Green
Write-Host "Frontend successfully deployed!" -ForegroundColor Green
Write-Host "URL: $frontendUrl" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
