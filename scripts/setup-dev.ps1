param(
    [string]$IndexUrl = "",
    [switch]$UseLockFiles
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath ".venv")) {
    python -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"

& $python -m pip install --upgrade pip

if ($IndexUrl -ne "") {
    & $python -m pip config --site set global.index-url $IndexUrl
}

if ($UseLockFiles) {
    & $python -m pip install -r requirements\dev.lock.txt
} else {
    & $python -m pip install -e ".[dev]"
}

Write-Output "Environment ready."

