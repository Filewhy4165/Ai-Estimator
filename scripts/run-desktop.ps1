param(
    [switch]$ShowLauncherWindow
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")
$venv = Join-Path $root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    throw ".venv not found. Run .\scripts\setup-dev.ps1 first."
}

$exe = Join-Path $venv "Scripts\ai-estimator-desktop.exe"
$python = Join-Path $venv "Scripts\python.exe"
$pythonw = Join-Path $venv "Scripts\pythonw.exe"
$windowStyle = if ($ShowLauncherWindow) { "Normal" } else { "Hidden" }

if ((-not $ShowLauncherWindow) -and (Test-Path -LiteralPath $pythonw)) {
    Start-Process -FilePath $pythonw -ArgumentList "-m", "desktop.app" -WorkingDirectory $root
    return
}

if (Test-Path -LiteralPath $exe) {
    Start-Process -FilePath $exe -WorkingDirectory $root -WindowStyle $windowStyle
    return
}

if (Test-Path -LiteralPath $python) {
    Start-Process -FilePath $python -ArgumentList "-m", "desktop.app" -WorkingDirectory $root -WindowStyle $windowStyle
    return
}

throw "Could not find ai-estimator-desktop launcher or python in $venv."
