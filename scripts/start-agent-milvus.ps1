[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$RecreateMilvus,
    [string]$MilvusDataRoot = $(if ($env:MILVUS_DATA_ROOT) { $env:MILVUS_DATA_ROOT } else { "E:\milvus-data" }),
    [string]$ComposePluginUrl = $(if ($env:DOCKER_COMPOSE_PLUGIN_URL) { $env:DOCKER_COMPOSE_PLUGIN_URL } else { "https://github.com/docker/compose/releases/latest/download/docker-compose-windows-x86_64.exe" })
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$ComposeFile = Join-Path $RepoRoot "docker-compose.milvus.yml"
$ComposeProject = "agent"
$EtcdName = "psych-agent-milvus-etcd"
$MinioName = "psych-agent-milvus-minio"
$MilvusName = "psych-agent-milvus-standalone"

function Write-Step {
    param([string]$Message)
    Write-Host "[agent-milvus] $Message"
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [switch]$AllowFailure
    )

    $line = "$FilePath $($ArgumentList -join ' ')"
    if ($DryRun) {
        Write-Host "[dry-run] $line"
        return 0
    }

    & $FilePath @ArgumentList
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "Command failed with exit code ${code}: ${line}"
    }
    return $code
}

function Test-ExternalSuccess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )
    try {
        & $FilePath @ArgumentList *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Wait-Docker {
    if ($DryRun) {
        Write-Host "[dry-run] docker version"
        return
    }

    if (Test-ExternalSuccess "docker" @("version", "--format", "{{.Server.Version}}")) {
        return
    }

    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Write-Step "Docker is not ready; starting Docker Desktop."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden | Out-Null
    }

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        if (Test-ExternalSuccess "docker" @("version", "--format", "{{.Server.Version}}")) {
            return
        }
    }

    throw "Docker did not become ready within 120 seconds."
}

function Install-DockerComposePlugin {
    $pluginDir = Join-Path $env:USERPROFILE ".docker\cli-plugins"
    $pluginPath = Join-Path $pluginDir "docker-compose.exe"
    $bundledCandidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\cli-plugins\docker-compose.exe"),
        (Join-Path $env:ProgramFiles "Docker\cli-plugins\docker-compose.exe"),
        (Join-Path $env:ProgramData "Docker\cli-plugins\docker-compose.exe")
    )

    if ($DryRun) {
        Write-Host "[dry-run] New-Item -ItemType Directory -Force $pluginDir"
        Write-Host "[dry-run] copy bundled Docker Desktop compose plugin if present"
        Write-Host "[dry-run] otherwise download $ComposePluginUrl to $pluginPath"
        return
    }

    New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
    foreach ($candidate in $bundledCandidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            Write-Step "Installing docker compose plugin from $candidate."
            Copy-Item -LiteralPath $candidate -Destination $pluginPath -Force
            return
        }
    }

    Write-Step "Downloading docker compose plugin from GitHub."
    Invoke-WebRequest -UseBasicParsing -Uri $ComposePluginUrl -OutFile $pluginPath
}

function Ensure-DockerComposePlugin {
    if ($DryRun) {
        Write-Host "[dry-run] docker compose version"
        return
    }

    if (Test-ExternalSuccess "docker" @("compose", "version")) {
        return
    }

    Write-Step "docker compose plugin is unavailable; installing it."
    Install-DockerComposePlugin

    if (-not (Test-ExternalSuccess "docker" @("compose", "version"))) {
        throw "docker compose plugin installation finished, but 'docker compose version' is still unavailable."
    }
}

function Wait-Http {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 90
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
    throw "Timed out waiting for $Url."
}

function Start-AgentMilvus {
    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        throw "Milvus compose file not found: $ComposeFile"
    }

    foreach ($path in @(
        (Join-Path $MilvusDataRoot "etcd"),
        (Join-Path $MilvusDataRoot "minio"),
        (Join-Path $MilvusDataRoot "milvus")
    )) {
        if ($DryRun) {
            Write-Host "[dry-run] New-Item -ItemType Directory -Force $path"
        } else {
            New-Item -ItemType Directory -Force -Path $path | Out-Null
        }
    }

    Wait-Docker
    Ensure-DockerComposePlugin

    if ($RecreateMilvus) {
        Write-Step "Recreating agent Milvus containers while keeping bind-mounted data under $MilvusDataRoot."
        Invoke-External "docker" @("compose", "-p", $ComposeProject, "-f", $ComposeFile, "down") | Out-Null
    }

    Write-Step "Starting agent Milvus compose project '$ComposeProject'."
    Invoke-External "docker" @("compose", "-p", $ComposeProject, "-f", $ComposeFile, "up", "-d") | Out-Null
    Wait-Http "http://127.0.0.1:9091/healthz" 120

    Write-Step "Agent Milvus entrypoint is ready."
    Write-Host "Milvus containers: $EtcdName, $MinioName, $MilvusName"
    Write-Host "Milvus data:       $MilvusDataRoot"
    Write-Host "Milvus health:     http://127.0.0.1:9091/healthz"
    Write-Host "Milvus gRPC:       127.0.0.1:19530"
}

Start-AgentMilvus
