[CmdletBinding()]
param(
    [switch]$DryRun,
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

function Write-Step {
    param([string]$Message)
    Write-Host "[backend] $Message"
}

function Test-PortListening {
    param([int]$Port)
    try {
        return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Wait-Http {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 60,
        [switch]$Optional
    )

    if ($DryRun) {
        Write-Host "[dry-run] wait for $Url"
        return
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    if ($Optional) {
        Write-Step "Timed out waiting for $Url; service may still be starting."
        return
    }
    throw "Timed out waiting for $Url."
}

$backendDir = Join-Path $RepoRoot "backend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
$stdout = Join-Path $backendDir "uvicorn.local.out.log"
$stderr = Join-Path $backendDir "uvicorn.local.err.log"
$args = @("-m", "uvicorn", "app.main:app", "--reload", "--port", "$BackendPort")

if ($DryRun) {
    Write-Host "[dry-run] Start-Process $python -m uvicorn app.main:app --reload --port $BackendPort"
    Write-Step "Backend entrypoint is ready."
    Write-Host "Backend: http://127.0.0.1:$BackendPort"
    return
}

if (Test-PortListening $BackendPort) {
    Write-Step "Backend port $BackendPort is already listening; leaving it alone."
    Write-Step "Backend entrypoint is ready."
    Write-Host "Backend: http://127.0.0.1:$BackendPort"
    return
}

Write-Step "Starting backend on http://127.0.0.1:$BackendPort."
Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $backendDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden | Out-Null
Wait-Http "http://127.0.0.1:$BackendPort/health" 60 -Optional
Write-Step "Backend entrypoint is ready."
Write-Host "Backend: http://127.0.0.1:$BackendPort"
