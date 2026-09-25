<#
.SYNOPSIS
    Orchestrates full-stack deployment of both backend and frontend to Google Cloud Run.

.DESCRIPTION
    Runs deploy-backend.ps1 followed by deploy-frontend.ps1 in sequence, passing through
    optional ProjectId and Region parameters.

.PARAMETER ProjectId
    Optional Google Cloud Project ID override.

.PARAMETER Region
    Optional Google Cloud Region override (defaults to asia-northeast1).

.EXAMPLE
    .\deploy\deploy-all.ps1

.EXAMPLE
    .\deploy\deploy-all.ps1 -ProjectId "my-gcp-project" -Region "asia-northeast1"
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $false, HelpMessage = "Google Cloud Project ID")]
    [string]$ProjectId,

    [Parameter(Mandatory = $false, HelpMessage = "Google Cloud Region")]
    [string]$Region = "asia-northeast1"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Build parameter hash to forward to child scripts
$forwardParams = @{}
if ($ProjectId) { $forwardParams['ProjectId'] = $ProjectId }
if ($PSBoundParameters.ContainsKey('Region')) { $forwardParams['Region'] = $Region }

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Starting Full-Stack Deployment (PowerShell)" -ForegroundColor Cyan
Write-Host "Step 1/2: Deploy Backend" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

& (Join-Path $scriptDir "deploy-backend.ps1") @forwardParams

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Step 2/2: Deploy Frontend" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

& (Join-Path $scriptDir "deploy-frontend.ps1") @forwardParams

Write-Host "==========================================" -ForegroundColor Green
Write-Host "Full-Stack Deployment Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
