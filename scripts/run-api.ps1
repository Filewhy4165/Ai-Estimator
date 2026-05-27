param()

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")
$venv = Join-Path $root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    throw ".venv not found. Run .\scripts\setup-dev.ps1 first."
}

$exe = Join-Path $venv "Scripts\ai-estimator-api.exe"
$python = Join-Path $venv "Scripts\python.exe"

if (Test-Path -LiteralPath $exe) {
    & $exe
    return
}

if (Test-Path -LiteralPath $python) {
    & $python -m service.run_api
    return
}

throw "Could not find ai-estimator-api launcher or python in $venv."
