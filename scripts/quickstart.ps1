param(
    [string]$PdfPath = "",
    [string]$ApiBase = "http://127.0.0.1:8000",
    [int]$MaxWaitSeconds = 300,
    [int]$PollIntervalSeconds = 2,
    [string]$AnalysisMode = "auto",
    [string]$SelectedTrades = "",
    [string]$Notes = "",
    [bool]$AutoStartApi = $true,
    [switch]$SkipApi,
    [switch]$SkipDesktop,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")
$venv = Join-Path $root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    throw ".venv not found. Run .\scripts\setup-dev.ps1 first."
}

if ($SkipApi -and $SkipDesktop) {
    throw "Nothing to start. Remove both -SkipApi and -SkipDesktop, or use -SkipSmoke only."
}

if ($SkipSmoke -and [string]::IsNullOrWhiteSpace($PdfPath)) {
    $PdfPath = ""
}

if ($PdfPath -and -not (Test-Path -LiteralPath $PdfPath)) {
    throw "PDF path not found: $PdfPath"
}

if ($MaxWaitSeconds -lt 20 -or $PollIntervalSeconds -lt 1) {
    throw "MaxWaitSeconds must be >= 20 and PollIntervalSeconds >= 1."
}

function Test-ApiHealth {
    param([string]$base, [int]$timeout = 2)
    $response = $null
    try {
        $request = [System.Net.WebRequest]::Create("$base/health")
        $request.Timeout = $timeout * 1000
        $request.Method = "GET"
        $response = $request.GetResponse()
        return $response.StatusCode -eq [System.Net.HttpStatusCode]::OK
    } catch {
        return $false
    } finally {
        if ($response) {
            $response.Close()
        }
    }
}

function Start-Api {
    $apiExe = Join-Path $venv "Scripts\ai-estimator-api.exe"
    $python = Join-Path $venv "Scripts\python.exe"
    if (Test-Path -LiteralPath $apiExe) {
        Start-Process -FilePath $apiExe -WorkingDirectory $root -WindowStyle Normal
        return
    }

    if (Test-Path -LiteralPath $python) {
        Start-Process -FilePath $python -ArgumentList "-m", "service.run_api" -WorkingDirectory $root -WindowStyle Normal
        return
    }

    throw "Could not find API launcher."
}

function Start-Desktop {
    $desktopExe = Join-Path $venv "Scripts\ai-estimator-desktop.exe"
    $python = Join-Path $venv "Scripts\python.exe"

    if (Test-Path -LiteralPath $desktopExe) {
        Start-Process -FilePath $desktopExe -WorkingDirectory $root -WindowStyle Normal
        return
    }

    if (Test-Path -LiteralPath $python) {
        Start-Process -FilePath $python -ArgumentList "-m", "desktop.app" -WorkingDirectory $root -WindowStyle Normal
        return
    }

    throw "Could not find desktop launcher."
}

$api_started_by_this_script = $false
if (-not $SkipApi) {
    if (-not (Test-ApiHealth -base $ApiBase -timeout 2)) {
        if ($AutoStartApi -or $PdfPath) {
            Start-Api
            $deadline = (Get-Date).AddSeconds(20)
            while ((Get-Date) -lt $deadline) {
                if (Test-ApiHealth -base $ApiBase -timeout 2) {
                    break
                }
                Start-Sleep -Milliseconds 500
            }
            if (-not (Test-ApiHealth -base $ApiBase -timeout 2)) {
                throw "API did not become ready after start attempt."
            }
            $api_started_by_this_script = $true
        } else {
            throw "API not reachable at $ApiBase. Start it first or set -AutoStartApi.`$true."
        }
    } else {
        Write-Output "API already reachable at $ApiBase."
    }
}

if (-not $SkipDesktop) {
    if ($api_started_by_this_script -and -not $SkipApi) {
        Start-Sleep -Seconds 2
    }
    Start-Desktop
}

if ($PdfPath -and -not $SkipSmoke) {
    $smokeArgs = @{
        PdfPath = (Resolve-Path -LiteralPath $PdfPath).Path
        ApiBase = $ApiBase
        MaxWaitSeconds = $MaxWaitSeconds
        PollIntervalSeconds = $PollIntervalSeconds
        AnalysisMode = $AnalysisMode
        SelectedTrades = $SelectedTrades
        Notes = $Notes
    }

    if ((-not (Test-ApiHealth -base $ApiBase -timeout 2)) -and $AutoStartApi) {
        $smokeArgs["StartApi"] = $true
    }

    & (Join-Path $PSScriptRoot "smoke-job.ps1") @smokeArgs
}

Write-Output "Quickstart complete."
