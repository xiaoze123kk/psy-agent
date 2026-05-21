[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipMilvus,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$RecreateMilvus,
    [string]$MilvusDataRoot = $(if ($env:MILVUS_DATA_ROOT) { $env:MILVUS_DATA_ROOT } else { "E:\milvus-data" }),
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step {
    param([string]$Message)
    Write-Host "[start-local] $Message"
}

function Invoke-StartupScript {
    param(
        [string]$ScriptName,
        [string[]]$Arguments = @()
    )

    $scriptPath = Join-Path $ScriptDir $ScriptName
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath) + $Arguments
    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "${ScriptName} failed with exit code $LASTEXITCODE."
    }
}

if ($DryRun) {
    Write-Step "Dry run enabled."
}

if ($SkipMilvus) {
    Write-Step "Skipping Milvus."
} else {
    $milvusArgs = @("-MilvusDataRoot", $MilvusDataRoot)
    if ($DryRun) {
        $milvusArgs += "-DryRun"
    }
    if ($RecreateMilvus) {
        $milvusArgs += "-RecreateMilvus"
    }
    Invoke-StartupScript "start-agent-milvus.ps1" $milvusArgs
}

if ($SkipBackend) {
    Write-Step "Skipping backend."
} else {
    $backendArgs = @("-BackendPort", "$BackendPort")
    if ($DryRun) {
        $backendArgs += "-DryRun"
    }
    Invoke-StartupScript "start-backend.ps1" $backendArgs
}

if ($SkipFrontend) {
    Write-Step "Skipping frontend."
} else {
    $frontendArgs = @("-FrontendPort", "$FrontendPort")
    if ($DryRun) {
        $frontendArgs += "-DryRun"
    }
    Invoke-StartupScript "start-frontend.ps1" $frontendArgs
}

Write-Step "Local stack entrypoint is ready."
Write-Host "Backend:  http://127.0.0.1:$BackendPort"
Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
Write-Host "Milvus:   http://127.0.0.1:9091/healthz and 127.0.0.1:19530"
