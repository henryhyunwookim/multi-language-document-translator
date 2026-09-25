<#
.SYNOPSIS
    Creates the backend's dedicated Cloud Run runtime identity.

.DESCRIPTION
    Grants the service account access only to the translator's existing data
    bucket. It does not create, move, or delete buckets or their contents.
#>
[CmdletBinding()]
param(
    [string]$ProjectId,
    [string]$BucketName
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectId) { $ProjectId = (gcloud config get-value project 2>$null).Trim() }
if (-not $ProjectId -or $ProjectId -eq '(unset)') { throw 'Set a GCP project or pass -ProjectId.' }
if (-not $BucketName) { $BucketName = "$ProjectId-document-translator-data" }

$accountId = 'translator-runtime'
$serviceAccount = "$accountId@$ProjectId.iam.gserviceaccount.com"
$describe = gcloud iam service-accounts describe $serviceAccount --project $ProjectId 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud iam service-accounts create $accountId --project $ProjectId --display-name 'Document Translator runtime'
    if ($LASTEXITCODE -ne 0) { throw 'Could not create runtime identity.' }
}

# Runtime storage operations are limited to this bucket; no Secret Manager role is granted.
gcloud storage buckets add-iam-policy-binding "gs://$BucketName" `
    --member="serviceAccount:$serviceAccount" `
    --role='roles/storage.objectAdmin'
if ($LASTEXITCODE -ne 0) { throw 'Could not grant bucket-scoped storage access.' }

Write-Host "Runtime identity ready: $serviceAccount"
Write-Host 'Deploy the backend with deploy-backend.ps1 after granting the deployer roles/iam.serviceAccountUser on this identity.'
