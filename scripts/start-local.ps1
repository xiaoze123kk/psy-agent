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
$RepoRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $RepoRoot "backend"

function Write-Step {
    param([string]$Message)
    Write-Host "[start-local] $Message"
}

function ConvertTo-YesNo {
    param([bool]$Value)
    if ($Value) { return "yes" }
    return "no"
}

function Read-BackendEnvFile {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }

        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim().TrimStart([char]0xFEFF)
        $value = $parts[1].Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$key] = $value
    }

    return $values
}

function Test-ProcessEnvKey {
    param([string]$Key)
    return [Environment]::GetEnvironmentVariables("Process").Contains($Key)
}

function Get-BackendEnvValue {
    param(
        [string]$Key,
        [string]$Default = ""
    )

    if (Test-ProcessEnvKey $Key) {
        return [Environment]::GetEnvironmentVariable($Key, "Process")
    }

    $envValue = $Default
    $envFile = Read-BackendEnvFile (Join-Path $BackendDir ".env")
    if ($envFile.ContainsKey($Key)) {
        $envValue = $envFile[$Key]
    }

    $envLocalFile = Read-BackendEnvFile (Join-Path $BackendDir ".env.local")
    if ($envLocalFile.ContainsKey($Key)) {
        $envValue = $envLocalFile[$Key]
    }

    return $envValue
}

function Get-SearchProviderSequence {
    param(
        [string]$Provider,
        [bool]$HasBingApiKey
    )

    $normalized = $Provider.Trim().ToLowerInvariant()
    if (-not $normalized) {
        $normalized = "bing_web"
    }

    $sequence = [System.Collections.Generic.List[string]]::new()
    function Add-Provider {
        param([string]$Name)
        if (-not $sequence.Contains($Name)) {
            [void]$sequence.Add($Name)
        }
    }

    if ($normalized -in @("auto", "bing_web", "bing")) {
        if ($HasBingApiKey) {
            Add-Provider "bing_api"
        }
        Add-Provider "bing_web"
        Add-Provider "sogou_web"
        Add-Provider "baidu_mobile"
        Add-Provider "ddg"
    } elseif ($normalized -eq "bing_api") {
        Add-Provider "bing_api"
        Add-Provider "bing_web"
        Add-Provider "sogou_web"
        Add-Provider "baidu_mobile"
        Add-Provider "ddg"
    } elseif ($normalized -in @("sogou", "sogou_web")) {
        Add-Provider "sogou_web"
        Add-Provider "bing_web"
        Add-Provider "ddg"
    } elseif ($normalized -in @("baidu", "baidu_mobile")) {
        Add-Provider "baidu_mobile"
        Add-Provider "sogou_web"
        Add-Provider "bing_web"
        Add-Provider "ddg"
    } elseif ($normalized -in @("ddg", "duckduckgo", "duckduckgo_search")) {
        Add-Provider "ddg"
    } else {
        Add-Provider "bing_web"
        Add-Provider "sogou_web"
        Add-Provider "baidu_mobile"
        Add-Provider "ddg"
    }

    return $sequence.ToArray()
}

function Write-SearchPreflight {
    $searchProvider = Get-BackendEnvValue "SEARCH_PROVIDER" "bing_web"
    $bingApiKey = Get-BackendEnvValue "BING_SEARCH_API_KEY" ""
    $bingEndpoint = Get-BackendEnvValue "BING_SEARCH_ENDPOINT" "https://api.bing.microsoft.com/v7.0/search"
    $searchProxy = Get-BackendEnvValue "SEARCH_PROXY" ""
    $hasBingApiKey = -not [string]::IsNullOrWhiteSpace($bingApiKey)
    $providerSequence = Get-SearchProviderSequence $searchProvider $hasBingApiKey
    $providerSet = @{}
    foreach ($providerName in $providerSequence) {
        $providerSet[$providerName] = $true
    }

    Write-Step "Search preflight."
    Write-Host "SEARCH_PROVIDER=$searchProvider"
    Write-Host "BING_SEARCH_API_KEY configured: $(ConvertTo-YesNo $hasBingApiKey)"
    Write-Host "BING_SEARCH_ENDPOINT=$bingEndpoint"
    Write-Host "SEARCH_PROXY configured: $(ConvertTo-YesNo (-not [string]::IsNullOrWhiteSpace($searchProxy)))"
    Write-Host "Chinese fallback chain: $($providerSequence -join ' -> ')"
    Write-Host "Fallback to Sogou: $(ConvertTo-YesNo $providerSet.ContainsKey('sogou_web')); Baidu: $(ConvertTo-YesNo $providerSet.ContainsKey('baidu_mobile')); DDG: $(ConvertTo-YesNo $providerSet.ContainsKey('ddg'))"

    $normalizedProvider = $searchProvider.Trim().ToLowerInvariant()
    if (-not $normalizedProvider) {
        $normalizedProvider = "bing_web"
    }
    if ($normalizedProvider -eq "bing_api" -and -not $hasBingApiKey) {
        Write-Step "Missing BING_SEARCH_API_KEY for SEARCH_PROVIDER=bing_api; Bing API will fail and the chain must rely on fallback providers."
    } elseif ($normalizedProvider -in @("auto", "bing_web", "bing") -and -not $hasBingApiKey) {
        Write-Step "BING_SEARCH_API_KEY is empty; Bing API will be skipped and Bing Web/Sogou/Baidu/DDG fallback remains available."
    }
    if ($normalizedProvider -in @("ddg", "duckduckgo", "duckduckgo_search")) {
        Write-Step "SEARCH_PROVIDER=$searchProvider uses DDG only; set SEARCH_PROVIDER=bing_web or auto for Sogou/Baidu fallback on Chinese time-sensitive queries."
    }
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

Write-SearchPreflight

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
