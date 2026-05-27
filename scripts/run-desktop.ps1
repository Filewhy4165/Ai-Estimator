param()

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")
$venv = Join-Path $root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    throw ".venv not found. Run .\scripts\setup-dev.ps1 first."
}

$exe = Join-Path $venv "Scripts\ai-estimator-desktop.exe"
$python = Join-Path $venv "Scripts\python.exe"

if (Test-Path -LiteralPath $exe) {
    & $exe
    return
}

if (Test-Path -LiteralPath $python) {
    & $python -m desktop.app
    return
}

throw "Could not find ai-estimator-desktop launcher or python in $venv."
