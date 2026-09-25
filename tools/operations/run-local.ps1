<#
.SYNOPSIS
    Start, check, or configure the local document translator.
.DESCRIPTION
    Runs the FastAPI backend and Next.js frontend as owned child process trees.
    Ctrl+C shuts down both services and their descendants.
.PARAMETER Mode
    Select Web, Desktop, Setup, or Check. Defaults to Web.
.PARAMETER ApiPort
    Loopback port for the API in Web mode. Defaults to 8080.
.PARAMETER WebPort
    Loopback port for the frontend in Web mode. Defaults to 3000.
.EXAMPLE
    .\tools\operations\run-local.ps1
.EXAMPLE
    .\tools\operations\run-local.ps1 -Mode Setup
#>
[CmdletBinding()]
param(
    [ValidateSet('Web', 'Desktop', 'Setup', 'Check')]
    [string]$Mode = 'Web',
    [int]$ApiPort = 8080,
    [int]$WebPort = 3000
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
$serviceWrapper = Join-Path $projectDirectory 'tools\operations\local_service.py'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable exited with code $LASTEXITCODE." }
}

Push-Location $projectDirectory
try {
    if ($Mode -eq 'Setup') {
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            $candidates = @((Get-Command python.exe -ErrorAction SilentlyContinue).Source)
            $candidates += @(Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
            $basePython = $candidates | Where-Object { $_ -and $_ -notlike '*\WindowsApps\*' } | Select-Object -First 1
            if (-not $basePython) { throw 'Install Python 3.11 or newer, then run -Mode Setup again.' }
            Invoke-Checked $basePython @('-m', 'venv', '.venv')
        }
        Invoke-Checked $pythonPath @('-m', 'pip', '--isolated', 'install', '-r', 'requirements.txt')
        Push-Location (Join-Path $projectDirectory 'frontend')
        try { Invoke-Checked 'npm.cmd' @('ci') } finally { Pop-Location }
        Write-Host 'Dependencies installed. Run .\tools\operations\run-local.ps1 -Mode Check, then .\tools\operations\run-local.ps1.'
        return
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run .\tools\operations\run-local.ps1 -Mode Setup first.' }
    if (-not $env:OFFICE_RENDERER) {
        foreach ($candidate in @("$env:ProgramFiles\LibreOffice\program\soffice.exe", "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe")) {
            if (Test-Path -LiteralPath $candidate) { $env:OFFICE_RENDERER = $candidate; break }
        }
    }
    if (-not $env:TRANSLATOR_JOB_DIR) { $env:TRANSLATOR_JOB_DIR = Join-Path $env:LOCALAPPDATA 'DocumentTranslator\jobs' }
    if ($Mode -eq 'Check') {
        Invoke-Checked $pythonPath @('-m', 'pip', 'check')
        Invoke-Checked $pythonPath @('tools/operations/check_local.py')
        return
    }
    if ($Mode -eq 'Desktop') {
        Invoke-Checked $pythonPath @($serviceWrapper, "$PID", $pythonPath, 'backend/main.py')
        return
    }
    $nodePath = (Get-Command node.exe -ErrorAction Stop).Source
    $nextPath = Join-Path $projectDirectory 'frontend\node_modules\next\dist\bin\next'
    if (-not (Test-Path -LiteralPath $nextPath)) { throw 'Run .\tools\operations\run-local.ps1 -Mode Setup to install frontend dependencies.' }
    foreach ($port in @($ApiPort, $WebPort)) {
        if ($port -lt 1 -or $port -gt 65535) { throw "Invalid port: $port" }
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
        try { $listener.Start() } catch { throw "Port $port is already in use. Stop that service or choose another port." }
        finally { $listener.Stop() }
    }
    if ($ApiPort -eq $WebPort) { throw 'API and web ports must be different.' }
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$ApiPort"
    $env:NEXT_TELEMETRY_DISABLED = '1'
    $logDirectory = Join-Path $env:LOCALAPPDATA ('DocumentTranslator\logs\' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $children = @()
    try {
        $children += Start-Process -FilePath $pythonPath -ArgumentList @("`"$serviceWrapper`"", "$PID", "`"$pythonPath`"", '-m', 'uvicorn', 'backend.api:app', '--host', '127.0.0.1', '--port', "$ApiPort") `
            -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logDirectory 'api.log') -RedirectStandardError (Join-Path $logDirectory 'api-error.log')
        $children += Start-Process -FilePath $pythonPath -ArgumentList @("`"$serviceWrapper`"", "$PID", "`"$nodePath`"", "`"$nextPath`"", 'dev', '--hostname', '127.0.0.1', '--port', "$WebPort") `
            -WorkingDirectory (Join-Path $projectDirectory 'frontend') -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logDirectory 'web.log') -RedirectStandardError (Join-Path $logDirectory 'web-error.log')
        $deadline = [DateTime]::UtcNow.AddMinutes(2)
        $ready = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            foreach ($child in $children) { if ($child.HasExited) { throw "A local service exited. See logs in $logDirectory" } }
            try {
                $null = Invoke-WebRequest "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 3
                $null = Invoke-WebRequest "http://127.0.0.1:$WebPort" -UseBasicParsing -TimeoutSec 10
                $ready = $true
                break
            } catch { Start-Sleep -Seconds 1 }
        }
        if (-not $ready) { throw "Local startup timed out. See logs in $logDirectory" }
        Write-Host "Translator: http://127.0.0.1:$WebPort"
        Write-Host "API docs:   http://127.0.0.1:$ApiPort/docs"
        Write-Host "Logs:       $logDirectory"
        Write-Host 'Press Ctrl+C to stop both services. Enter a Gemini API key in the app, or choose Google Translate.'
        while ($true) {
            foreach ($child in $children) { if ($child.HasExited) { throw "A service stopped. See $logDirectory" } }
            Start-Sleep -Seconds 1
        }
    } finally {
        foreach ($child in $children) {
            if (-not $child.HasExited) { & taskkill.exe /PID $child.Id /T /F | Out-Null }
        }
    }
} finally { Pop-Location }
