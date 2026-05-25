[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipStart,
    [string]$MilvusDataRoot = $(if ($env:MILVUS_DATA_ROOT) { $env:MILVUS_DATA_ROOT } else { "E:\milvus-data" }),
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $RepoRoot "backend"
$BackendSmokeScript = Join-Path $BackendDir "scripts\live_smoke.py"

function Write-Step {
    param([string]$Message)
    Write-Host "[live-smoke] $Message"
}

function ConvertFrom-Utf8Base64 {
    param([string]$Value)
    return [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}

function Invoke-StartupScript {
    $scriptPath = Join-Path $ScriptDir "start-local.ps1"
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $scriptPath,
        "-MilvusDataRoot",
        $MilvusDataRoot,
        "-BackendPort",
        "$BackendPort",
        "-FrontendPort",
        "$FrontendPort"
    )
    if ($DryRun) {
        $args += "-DryRun"
    }

    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "start-local.ps1 failed with exit code $LASTEXITCODE."
    }
}

if ($DryRun) {
    Write-Step "Dry run enabled."
}

if ($SkipStart) {
    Write-Step "Skipping local stack startup."
} else {
    Write-Step "Starting local stack before live smoke."
    Invoke-StartupScript
}

$venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
$smokeArgs = @(
    $BackendSmokeScript,
    "--backend-url",
    "http://127.0.0.1:$BackendPort",
    "--frontend-url",
    "http://127.0.0.1:$FrontendPort",
    "--milvus-health-url",
    "http://127.0.0.1:9091/healthz",
    "--timeout-seconds",
    "$TimeoutSeconds"
)

if ($DryRun) {
    Write-Step "Would run backend live smoke: $python $($smokeArgs -join ' ')"
    Write-Host "Queries:"
    Write-Host "- $(ConvertFrom-Utf8Base64 '5byg6Zuq5bOw5Y675LiW5pe26Ze05piv5LuA5LmI77yf')"
    Write-Host "- $(ConvertFrom-Utf8Base64 '54m55pyX5pmu6K6/5Y2O5piv5LuA5LmI5pe25YCZ77yf')"
    return
}

Write-Step "Running backend live smoke."
Push-Location $BackendDir
try {
    & $python @smokeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "backend live smoke failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
