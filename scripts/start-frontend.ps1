[CmdletBinding()]
param(
    [switch]$DryRun,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

function Write-Step {
    param([string]$Message)
    Write-Host "[frontend] $Message"
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
        [int]$TimeoutSeconds = 45,
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

$frontendDir = Join-Path $RepoRoot "frontend"
$stdout = Join-Path $frontendDir "vite.local.out.log"
$stderr = Join-Path $frontendDir "vite.local.err.log"
$args = @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort")

if ($DryRun) {
    Write-Host "[dry-run] Start-Process npm.cmd run dev -- --host 127.0.0.1 --port $FrontendPort"
    Write-Step "Frontend entrypoint is ready."
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
    return
}

if (Test-PortListening $FrontendPort) {
    Write-Step "Frontend port $FrontendPort is already listening; leaving it alone."
    Write-Step "Frontend entrypoint is ready."
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
    return
}

Write-Step "Starting frontend on http://127.0.0.1:$FrontendPort."
Start-Process -FilePath "npm.cmd" -ArgumentList $args -WorkingDirectory $frontendDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden | Out-Null
Wait-Http "http://127.0.0.1:$FrontendPort" 45 -Optional
Write-Step "Frontend entrypoint is ready."
Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
