param(
    [switch]$SkipApi,
    [switch]$SkipDesktop
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")
$venv = Join-Path $root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    throw ".venv not found. Run .\scripts\setup-dev.ps1 first."
}

$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable not found in $venv."
}

if ($SkipApi -and $SkipDesktop) {
    throw "Nothing to launch. Remove both -SkipApi and -SkipDesktop or run one component."
}

function Start-Command {
    param(
        [string]$command,
        [string]$arguments = ""
    )
    if ([string]::IsNullOrWhiteSpace($arguments)) {
        Start-Process -FilePath $command -WorkingDirectory $root
    } else {
        Start-Process -FilePath $command -ArgumentList $arguments -WorkingDirectory $root
    }
}

function Resolve-Command {
    param([string]$primaryExe, [string]$fallbackModule)
    if (Test-Path -LiteralPath $primaryExe) {
        return @($primaryExe, "")
    }

    if (Test-Path -LiteralPath $python) {
        return @($python, $fallbackModule)
    }

    return @("", "")
}

function Invoke-LaunchCommand {
    param(
        [string]$name,
        [string]$exe,
        [string]$arguments
    )
    if (-not $exe) {
        throw "Could not find launcher or python fallback for $name."
    }

    if (-not $arguments) {
        Start-Command -command $exe
    } else {
        Start-Command -command $exe -arguments $arguments
    }
}

if (-not $SkipApi) {
    $apiCmd = Resolve-Command -primaryExe (Join-Path $venv "Scripts\ai-estimator-api.exe") -fallbackModule "-m service.run_api"
    Invoke-LaunchCommand -name "API" -exe $apiCmd[0] -arguments $apiCmd[1]
    $api_started = $true
} else {
    $api_started = $false
}

if (-not $SkipDesktop) {
    if ($api_started) {
        Start-Sleep -Seconds 2
    }
    $desktopCmd = Resolve-Command -primaryExe (Join-Path $venv "Scripts\ai-estimator-desktop.exe") -fallbackModule "-m desktop.app"
    Invoke-LaunchCommand -name "Desktop" -exe $desktopCmd[0] -arguments $desktopCmd[1]
}

Write-Output "Launched full stack. API window and desktop window were started in separate windows."
