[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Reload,
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

function Get-ListeningProcess {
    param([int]$Port)
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $connection) {
        return $null
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Pid = $connection.OwningProcess
        CommandLine = if ($process) { [string]$process.CommandLine } else { "" }
    }
}

function Stop-ExistingBackend {
    param([int]$Port)

    $listener = Get-ListeningProcess $Port
    if ($null -eq $listener) {
        return
    }

    if ($listener.CommandLine -notmatch "uvicorn\s+app\.main:app") {
        Write-Step "Backend port $Port is already listening, but it is not the project backend; leaving it alone."
        return
    }

    if ($DryRun) {
        Write-Host "[dry-run] Stop-Process -Id $($listener.Pid) -Force"
        return
    }

    Write-Step "Stopping existing project backend on port $Port before starting a clean RAG-capable process."
    Stop-Process -Id $listener.Pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
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
$args = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort")
if ($Reload) {
    $args += "--reload"
}

$env:LOCAL_EMBEDDING_USE_WORKER = if ($env:LOCAL_EMBEDDING_USE_WORKER) { $env:LOCAL_EMBEDDING_USE_WORKER } else { "1" }
$env:EMBEDDING_TIMEOUT_SECONDS = if ($env:EMBEDDING_TIMEOUT_SECONDS) { $env:EMBEDDING_TIMEOUT_SECONDS } else { "120" }
$env:RAG_RETRIEVAL_TIMEOUT_SECONDS = if ($env:RAG_RETRIEVAL_TIMEOUT_SECONDS) { $env:RAG_RETRIEVAL_TIMEOUT_SECONDS } else { "30" }
$env:CHAT_TURN_TIMEOUT_SECONDS = if ($env:CHAT_TURN_TIMEOUT_SECONDS) { $env:CHAT_TURN_TIMEOUT_SECONDS } else { "120" }

if ($DryRun) {
    Write-Host "[dry-run] LOCAL_EMBEDDING_USE_WORKER=$env:LOCAL_EMBEDDING_USE_WORKER"
    Write-Host "[dry-run] EMBEDDING_TIMEOUT_SECONDS=$env:EMBEDDING_TIMEOUT_SECONDS"
    Write-Host "[dry-run] RAG_RETRIEVAL_TIMEOUT_SECONDS=$env:RAG_RETRIEVAL_TIMEOUT_SECONDS"
    Write-Host "[dry-run] CHAT_TURN_TIMEOUT_SECONDS=$env:CHAT_TURN_TIMEOUT_SECONDS"
    $reloadText = if ($Reload) { " --reload" } else { "" }
    Write-Host "[dry-run] Start-Process $python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort$reloadText"
    Write-Step "Backend entrypoint is ready."
    Write-Host "Backend: http://127.0.0.1:$BackendPort"
    return
}

Stop-ExistingBackend $BackendPort
if (Test-PortListening $BackendPort) {
    throw "Backend port $BackendPort is still listening after cleanup; stop that process or choose another port."
}

Write-Step "Starting backend on http://127.0.0.1:$BackendPort."
Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $backendDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden | Out-Null
Wait-Http "http://127.0.0.1:$BackendPort/health" 60 -Optional
Write-Step "Backend entrypoint is ready."
Write-Host "Backend: http://127.0.0.1:$BackendPort"
