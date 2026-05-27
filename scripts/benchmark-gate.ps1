param(
    [string]$ResultsDir = "benchmarks\\results",
    [double]$MinCandidateScore = [double]::NaN,
    [double]$MaxNegativeDelta = [double]::NaN,
    [bool]$RequireNonRegression = $true,
    [bool]$RequireImprovement = $false,
    [string]$ApiBase = "http://127.0.0.1:8000",
    [switch]$UseApi
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

$resultsPath = if ([System.IO.Path]::IsPathRooted($ResultsDir)) {
    Resolve-Path -LiteralPath $ResultsDir
} else {
    Resolve-Path -LiteralPath (Join-Path $root $ResultsDir)
}
if (-not (Test-Path -LiteralPath $resultsPath)) {
    throw "Results directory not found: $resultsPath"
}

function To-ApiBoolean {
    param([bool]$value)
    return $value.ToString().ToLower()
}

function To-PythonBoolean {
    param([bool]$value)
    if ($value) { return "True" }
    return "False"
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

function Invoke-ApiGate {
    param([string]$base)

    $query = [System.Text.StringBuilder]::new()
    $query.Append("results_dir=$([uri]::EscapeDataString($resultsPath))") | Out-Null

    if (-not [double]::IsNaN($MinCandidateScore)) {
        $query.AppendFormat("&min_candidate_score={0}", [double]$MinCandidateScore) | Out-Null
    }

    if (-not [double]::IsNaN($MaxNegativeDelta)) {
        $query.AppendFormat("&max_negative_delta={0}", [double]$MaxNegativeDelta) | Out-Null
    }

    $query.AppendFormat("&require_non_regression={0}", (To-ApiBoolean $RequireNonRegression)) | Out-Null
    $query.AppendFormat("&require_improvement={0}", (To-ApiBoolean $RequireImprovement)) | Out-Null

    $url = "$base/v1/benchmark-reports/gate?$query"
    try {
        $response = Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 30
        return $response
    } catch {
        throw "Benchmark gate API call failed. $($_.Exception.Message)"
    }
}

function Invoke-LocalGate {
    $minExpr = if ([double]::IsNaN($MinCandidateScore)) { "None" } else { [string]$MinCandidateScore }
    $maxExpr = if ([double]::IsNaN($MaxNegativeDelta)) { "None" } else { [string]$MaxNegativeDelta }
    $nonRegressionExpr = To-PythonBoolean $RequireNonRegression
    $improvementExpr = To-PythonBoolean $RequireImprovement

    $scriptPath = Join-Path $env:TEMP ("bench-gate-" + [Guid]::NewGuid().ToString() + ".py")
    @"
import json
from pathlib import Path
from ai_estimator.benchmark_compare import evaluate_latest_benchmark_quality_gate

result = evaluate_latest_benchmark_quality_gate(
    Path(r"""$($resultsPath)"""),
    min_candidate_score=$minExpr,
    max_negative_delta=$maxExpr,
    require_non_regression=$nonRegressionExpr,
    require_improvement=$improvementExpr,
)
print(json.dumps(result, indent=2))
"@ | Set-Content -Path $scriptPath -Encoding utf8

    try {
        $jsonLines = & $python $scriptPath
        $json = $jsonLines -join "`n"
    } finally {
        Remove-Item -Path $scriptPath -ErrorAction SilentlyContinue
    }

    return (ConvertFrom-Json -InputObject $json)
}

$payload = $null
if ($UseApi -and (Test-ApiHealth -base $ApiBase)) {
    $payload = Invoke-ApiGate -base $ApiBase
} elseif ($UseApi) {
    throw "Benchmark API not reachable at $ApiBase. Start it and retry, or run without -UseApi for local evaluation."
} else {
    $payload = Invoke-LocalGate
}

if ($null -eq $payload) {
    throw "Could not evaluate benchmark gate."
}

$status = if ($payload.passed) { "PASS" } else { "FAIL" }
Write-Output "Benchmark gate: $status"
Write-Output ($payload | ConvertTo-Json -Depth 30)

if (-not $payload.passed) {
    exit 1
}
