param(
    [Parameter(Mandatory = $true)]
    [string]$PdfPath,
    [string]$ApiBase = "http://127.0.0.1:8000",
    [int]$MaxWaitSeconds = 300,
    [int]$PollIntervalSeconds = 2,
    [string]$SelectedTrades = "",
    [string]$AnalysisMode = "auto",
    [string]$Notes = "",
    [switch]$StartApi
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")
$venv = Join-Path $root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    throw ".venv not found. Run .\scripts\setup-dev.ps1 first."
}

if (-not (Test-Path -LiteralPath $PdfPath)) {
    throw "PDF path not found: $PdfPath"
}

if ($MaxWaitSeconds -lt 20 -or $PollIntervalSeconds -lt 1) {
    throw "MaxWaitSeconds must be >= 20 and PollIntervalSeconds >= 1."
}

$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable not found in $venv."
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

if (-not (Test-ApiHealth $ApiBase 3)) {
    if ($StartApi) {
        Start-Api
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline) {
            if (Test-ApiHealth $ApiBase 3) {
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not (Test-ApiHealth $ApiBase 3)) {
            throw "API did not become ready after start attempt."
        }
    } else {
        throw "API not reachable at $ApiBase. Start it first or use -StartApi."
    }
}

$config = @{
    apiBase = $ApiBase
    pdf = (Resolve-Path -LiteralPath $PdfPath).Path
    analysisMode = $AnalysisMode
    selectedTrades = $SelectedTrades
    notes = $Notes
    maxWaitSeconds = $MaxWaitSeconds
    pollIntervalSeconds = $PollIntervalSeconds
} | ConvertTo-Json -Compress

$py = @"
import json
import requests
import time
import sys
import os

cfg_path = sys.argv[1]
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
base = cfg["apiBase"].rstrip("/")
pdf = cfg["pdf"]
analysis_mode = cfg["analysisMode"]
selected_trades = cfg["selectedTrades"]
notes = cfg["notes"]
max_wait = int(cfg["maxWaitSeconds"])
poll_interval = int(cfg["pollIntervalSeconds"])

payload = {
    "analysis_mode": analysis_mode,
    "selected_trades": selected_trades,
}
if notes:
    payload["notes"] = notes

with open(pdf, "rb") as f:
    response = requests.post(
        f"{base}/v1/jobs",
        data=payload,
        files=[("files", (os.path.basename(pdf), f, "application/pdf"))],
        timeout=120,
    )

print(response.status_code, end="\n")
text = response.text or ""
print(text)
if response.status_code >= 300:
    raise SystemExit(f"Submit failed: {response.status_code}")

j = response.json()
job_id = str(j.get("job_id", "")).strip()
if not job_id:
    raise SystemExit("No job_id in response.")

status = str(j.get("status", "")).strip()
for _ in range(0, max(1, int(max_wait / max(1, poll_interval)))):
    time.sleep(poll_interval)
    detail = requests.get(f"{base}/v1/jobs/{job_id}", timeout=30).json()
    status = str(detail.get("status", "")).strip()
    if status in {"completed", "failed", "canceled"}:
        break

result = j if status not in {"completed", "failed", "canceled"} else detail
print(json.dumps({
    "job_id": job_id,
    "status": status,
    "sheets_detected": len((result.get("result", {}) or {}).get("sheets_detected", [])),
    "rooms": len((result.get("result", {}) or {}).get("geometry", {}).get("annotations", {}).get("rooms", [])) if isinstance((result.get("result", {}) or {}).get("geometry", {}), dict) else 0,
    "unknown_symbols": len((result.get("result", {}) or {}).get("legend_and_symbols", {}).get("unknown_symbols", [])),
    "request_url": f"{base}/v1/jobs/{job_id}"
}, indent=2))

if status == "failed":
    raise SystemExit("Job failed.")

if status == "canceled":
    raise SystemExit("Job was canceled.")
if status != "completed":
    raise SystemExit(f"Job timed out or did not reach terminal status. status={status}")
"@

$pyPath = Join-Path $env:TEMP ("smoke-" + [Guid]::NewGuid().ToString() + ".py")
$cfgPath = Join-Path $env:TEMP ("smoke-" + [Guid]::NewGuid().ToString() + ".json")
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($cfgPath, $config, $utf8NoBom)
    Set-Content -LiteralPath $pyPath -Value $py -Encoding UTF8
    & $python $pyPath $cfgPath
    if ($LASTEXITCODE -ne 0) {
        throw "Smoke job script failed with exit code $LASTEXITCODE."
    }
} finally {
    if (Test-Path -LiteralPath $cfgPath) { Remove-Item -Force -LiteralPath $cfgPath }
    if (Test-Path -LiteralPath $pyPath) { Remove-Item -Force -LiteralPath $pyPath }
}
