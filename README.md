# AI Estimator

AI Estimator is an API-first system for converting construction drawing PDFs into:

- structured extraction data
- simplified 3D model data
- quantity takeoff buckets
- cost-mapping-ready outputs

The engine is intentionally conservative: it does not invent dimensions or geometry. Unknowns are logged in `issues_or_ambiguities`.

## Why this architecture is scalable

The estimator core is packaged once and exposed through:

- CLI (`ai-estimator`) for local processing
- API (`ai-estimator-api`) for desktop and future mobile apps
- Desktop client (`ai-estimator-desktop`) that calls the API

This separation means iOS and Android can reuse the same backend contracts with no rewrite of extraction logic.

## Repository layout

- `ai_estimator/` core extraction and output assembly
- `service/` FastAPI service for network clients
- `desktop/` desktop UI client that calls service endpoints
- `ai_estimator/schema/output_schema.json` strict output contract
- `tests/` core validation tests

## Install

```bash
pip install -e .
```

For reproducible installs with pinned versions:

```bash
pip install -r requirements/dev.lock.txt
```

## Run the API

```bash
ai-estimator-api
```

PowerShell fallback:

```powershell
.\.venv\Scripts\ai-estimator-api.exe
```

Or use the repo helper:

```powershell
.\scripts\run-api.ps1
```

CMD fallback:

```cmd
.\scripts\run-api.bat
```

Default URL: `http://127.0.0.1:8000`

## Run desktop app

```bash
ai-estimator-desktop
```

PowerShell fallback:

```powershell
.\.venv\Scripts\ai-estimator-desktop.exe
```

Or use the repo helper:

```powershell
.\scripts\run-desktop.ps1
```

CMD fallback:

```cmd
.\scripts\run-desktop.bat
```

Run both services in one command:

```powershell
.\scripts\run-full-stack.ps1
```

Run full stack and one smoke PDF automatically (desktop optional):

```powershell
.\scripts\quickstart.ps1 -PdfPath "C:\path\to\drawing.pdf"
```

Quickstart defaults:

- auto-starts API when needed
- starts desktop unless `-SkipDesktop`
- waits for desktop/API startup sequencing
- runs smoke by default when `PdfPath` is set

CMD fallback:

```cmd
.\scripts\run-full-stack.bat
```

Quickstart CMD fallback:

```cmd
.\scripts\quickstart.bat -PdfPath "C:\path\to\drawing.pdf"
```

Run without a smoke job:

```powershell
.\scripts\quickstart.ps1 -SkipSmoke -PdfPath "C:\path\to\drawing.pdf"
```

Run a one-pdf smoke test from CLI:

```powershell
.\scripts\smoke-job.ps1 -PdfPath "C:\path\to\drawing.pdf"
```

Start the API automatically if needed:

```powershell
.\scripts\smoke-job.ps1 -PdfPath "C:\path\to\drawing.pdf" -StartApi
```

Run benchmark quality gate against the latest two benchmark reports in `benchmarks\results`:

```powershell
.\scripts\benchmark-gate.ps1 -ResultsDir ".\benchmarks\results"
```

Require a minimum candidate score and fail on regression:

```powershell
.\scripts\benchmark-gate.ps1 -ResultsDir ".\benchmarks\results" -MinCandidateScore 0.85 -RequireNonRegression:$true
```

Run against the API endpoint instead (useful for CI or shared result folders):

```powershell
.\scripts\benchmark-gate.ps1 -UseApi -ApiBase "http://127.0.0.1:8000" -ResultsDir ".\benchmarks\results"
```

CMD fallback:

```cmd
.\scripts\smoke-job.bat "C:\path\to\drawing.pdf" -StartApi
.\scripts\benchmark-gate.bat -ResultsDir ".\benchmarks\results"
```

Run only API:

```powershell
.\scripts\run-full-stack.ps1 -SkipDesktop
```

Run only desktop:

```powershell
.\scripts\run-full-stack.ps1 -SkipApi
```

The desktop app supports both synchronous analysis and async job workflows.
It also remembers your last API URL, selected PDFs, overrides file, and current job ID between launches.
When API URL points to `127.0.0.1` or `localhost`, the app can auto-start the local API if the connection is refused.
If API key auth is enabled on the service, populate `API Key (optional)` in the desktop app so it sends `x-api-key`.
For security, the desktop app does not persist API keys to disk; set `AI_ESTIMATOR_API_KEY` in your shell to prefill each session.

Common startup issues:

- If PowerShell says `ai-estimator-desktop : The term ... was not recognized`, use:
  - `.\.venv\Scripts\ai-estimator-desktop.exe`
- If desktop reports API connection errors, start the API first with:
  - `.\scripts\run-api.ps1`
  - then retry desktop, or use `.\scripts\run-full-stack.ps1` to start both.
- If the desktop can not auto-start the API due to policy/security prompts, run in a fresh terminal and use:
  - `Set-ExecutionPolicy -Scope Process Bypass`

Desktop async workflow:

1. Click `Choose PDFs`
2. Click `Submit Async Job`
3. Click `Refresh Job` until status is `completed` (or enable `Auto Poll Job` to refresh automatically)
4. Click `Get Review Queue` to see flagged sheets
5. Click `Export Overrides Template` to save a prefilled JSON template for sheet corrections
6. Edit the template file, then load it in `Sheet Overrides JSON` and submit a new job
7. Use `Notes` for project-specific constraints before running
8. Use `Rerun Job` to reprocess an existing job ID without re-uploading PDFs
9. Use `Rerun Recommended` to auto-queue a rerun using AI-recommended trade scope (`selected` vs `all`)
10. Use `Export Benchmark Template` to create a prefilled benchmark manifest from a completed job
11. Use `Run Baseline Benchmark` to export a manifest and produce a scored benchmark report in one action
12. Use `Run End-to-End Benchmark` to submit selected PDFs, wait for completion, then auto-generate and score a benchmark report
13. Use `Show Benchmark History` to review recent benchmark reports (via API when available; local fallback otherwise) and `Open Results Folder` to access saved outputs
14. Use `Compare Reports` to compare two benchmark reports and see score deltas by metric (via API when available; local fallback otherwise)
15. Use `Compare Latest Reports` to automatically compare the two most recent benchmark reports (via API when available; local fallback otherwise)
16. Use `Latest Trend Snapshot` to get a compact benchmark trend summary (trend, delta, baseline/candidate scores)
17. Use `Score Timeline` to view recent benchmark scores with per-run deltas for charting/trend review
18. Use `Evaluate Gate` to run a benchmark quality gate (default: non-regression required)
19. Use `Benchmark Dashboard` to load history, timeline, latest trend, and gate evaluation in one response
20. Use `Job Ops Snapshot` to view queue depth, failure rate, 24h throughput, latency percentiles, and extraction quality signals for recent jobs
21. Use `Job Ops Gate` to evaluate pass/fail thresholds for operational health and extraction quality in one click
22. Use `Trade Recommendation` to get a confidence-scored recommendation for `selected` vs `all` trade analysis
23. Use `Trade Coverage` to validate per-trade detection, analysis, and quantity signal coverage before handoff
24. Use `Load Trades` to fetch canonical analysis modes and valid trade tokens from the API
25. Use `Validate Trades` to pre-check selected trade input before submit/rerun
26. Use `Readiness Report` for a single handoff decision based on review queue risk, trade coverage, recommendation, and ops gate

## Run CLI directly

```bash
ai-estimator ^
  --pdf "C:\path\to\drawings.pdf" ^
  --analysis-mode auto ^
  --output "C:\path\to\output.json"
```

Optional flags:

```bash
--selected-trades architectural,structural,mechanical_hvac
--sheet-overrides C:\path\to\sheet_overrides.json
--notes C:\path\to\notes.txt
--no-validate
```

## Run benchmark harness

Use the benchmark harness to score extraction quality on labeled drawing sets.

```bash
ai-estimator-benchmark ^
  --manifest ".\benchmarks\manifest.example.json" ^
  --output ".\benchmarks\results\latest.json"
```

Optional:

```bash
--fail-below 0.80
--no-validate
--schema-path C:\path\to\output_schema.json
```

## Compare benchmark reports

Use the benchmark comparison CLI to compare two reports directly or compare the latest pair in a folder.

```bash
ai-estimator-benchmark-compare ^
  --baseline ".\benchmarks\results\run_a.json" ^
  --candidate ".\benchmarks\results\run_b.json"
```

Latest two reports:

```bash
ai-estimator-benchmark-compare ^
  --latest ^
  --results-dir ".\benchmarks\results"
```

Optional quality gates:

```bash
--fail-on-regression
--max-negative-delta 0.05
```

Benchmark manifest shape:

- `defaults` shared run options (`analysis_mode`, `selected_trades`, optional `sheet_overrides`)
- `cases[]` list of benchmark runs
- `cases[].expected.sheet_ids` expected detected sheet IDs
- `cases[].expected.scales_by_sheet` expected scale string by sheet ID
- `cases[].expected.analyzed_trades` expected analyzed trade list
- `cases[].expected.quantity_sanity` optional checks:
  - `require_nonempty_counts` boolean
  - `min_total_count` integer
  - `min_counts_by_type` map of element type to minimum count

## API endpoints

- `GET /health`
- `GET /v1/meta/trades` supported `analysis_mode` values and valid trade catalog (with CSI defaults)
- `POST /v1/analyze` synchronous analysis
- `POST /v1/jobs` async job submission
- `POST /v1/jobs/{job_id}/rerun` async rerun using files from an existing job
- `POST /v1/jobs/{job_id}/rerun-recommended` async rerun using AI-recommended trade scope from the source job
- `POST /v1/jobs/{job_id}/cancel` cancel a queued/running job (`canceled` terminal status)
- `DELETE /v1/jobs/{job_id}` delete a terminal job record (`cleanup_uploads=true` optionally removes owned upload folders)
- `POST /v1/jobs/prune` bulk prune terminal jobs with filters (`statuses`, `older_than_hours`, `limit`, `dry_run`, optional upload cleanup)
- `GET /v1/jobs` list jobs (supports `limit`, `offset`, `status` including `canceled`)
- `GET /v1/jobs/capacity` live async queue/worker capacity snapshot
- `GET /v1/jobs/metrics` operations snapshot for recent jobs (status counts, active queue depth, failure rate, 24h throughput, latency distributions, and extraction quality signals)
- `GET /v1/jobs/metrics/gate` pass/fail gate over job metrics with configurable thresholds
- `GET /v1/jobs/{job_id}` job status/result
- `GET /v1/jobs/{job_id}/trade-recommendation` recommendation for `selected` vs `all` trade scope with confidence and rationale
- `GET /v1/jobs/{job_id}/trade-coverage` coverage table by trade (detected/analyzed/signals/status)
- `GET /v1/jobs/{job_id}/readiness-report` consolidated go/no-go handoff report
- `GET /v1/jobs/{job_id}/review-queue` prioritized review list for ambiguous sheets
- `GET /v1/jobs/{job_id}/sheet-overrides-template` prefilled override rows for unmapped/problem sheets
- `GET /v1/jobs/{job_id}/benchmark-template` prefilled benchmark manifest template from a completed job
- `GET /v1/benchmark-reports/history` list benchmark reports with pagination from a results directory
- `GET /v1/benchmark-reports/compare` compare two benchmark report JSON files
- `GET /v1/benchmark-reports/compare-latest` compare the two most recent valid benchmark reports in a results folder
- `GET /v1/benchmark-reports/trend` compact trend summary based on the latest two valid benchmark reports
- `GET /v1/benchmark-reports/timeline` recent score points with delta vs previous report
- `GET /v1/benchmark-reports/gate` quality gate evaluation for latest benchmark run pair
- `GET /v1/benchmark-reports/dashboard` combined benchmark history, timeline, trend, and gate payload

Sheet detection metadata:

- `sheets_detected[].sheet_id_source` indicates how a sheet ID was produced: `detected`, `override`, `inferred_facility_short`, or `unmapped`.

Optional form fields for `POST /v1/analyze` and `POST /v1/jobs`:

- `sheet_overrides_json` JSON array string such as:
  `[{"source_page_index":12,"sheet_id":"A101","title":"First Floor Plan"}]`
- `notes` free-text notes/constraints (trimmed to 2000 chars)
- when `analysis_mode=selected`, `selected_trades` must include at least one valid trade token

Optional form fields for `POST /v1/jobs/{job_id}/rerun`:

- `analysis_mode` (`auto`, `selected`, `all`) overrides source job mode
- `selected_trades` CSV overrides source job trades
- `sheet_overrides_json` overrides source job sheet overrides
- `notes` overrides source job notes

Notes on overrides:

- `source_page_index` is 1-based (page 1 is the first PDF page).
- If omitted, overrides are applied in list order as a fallback.

Review queue endpoint query params:

- `low_confidence_threshold` (default `0.75`, range `0..1`)
- `include_only_flagged` (default `true`)
- each queue item includes `sheet_id_source` and summary includes `sheet_id_source_counts`

Sheet overrides template endpoint query params:

- `include_all` (default `false`) include all sheets instead of only sheets needing manual correction
- default problem rows include unmapped IDs, invalid ID format, missing title, and low-confidence inferred sheet IDs
- each row includes `current_sheet_id_source` and summary includes `sheet_id_source_counts`

Example:

```bash
curl "http://127.0.0.1:8000/v1/jobs/<job_id>/sheet-overrides-template"
```

The response `items` can be edited and sent back as `sheet_overrides_json` in a new `POST /v1/jobs` request.
Benchmark template endpoint query params:

- `include_unmapped` (default `false`) include unmapped sheet IDs in `expected.sheet_ids`
- `case_id` optional override for the generated benchmark case ID

Example:

```bash
curl "http://127.0.0.1:8000/v1/jobs/<job_id>/benchmark-template"
```

The response includes `manifest`, which you can save directly as a benchmark manifest JSON and then refine expected labels.
The generated `quantity_sanity.min_total_count` is seeded from the source job's current total count baseline.
The rerun endpoint reuses files from the source job and returns `409` if those files were cleaned up or moved.
Cancel notes:

- Queued jobs are canceled immediately.
- Running jobs are marked `canceled` immediately; in-process computation is best-effort and completion updates are ignored.
- `DELETE /v1/jobs/{job_id}` only deletes terminal jobs (`completed`, `failed`, `canceled`) and returns `409` for active jobs.
- `POST /v1/jobs/prune` defaults to dry-run and terminal statuses only; active statuses are rejected.

Benchmark report compare endpoint examples:

```bash
curl "http://127.0.0.1:8000/v1/benchmark-reports/history?results_dir=C:\path\to\benchmarks\results&limit=20&offset=0"
curl "http://127.0.0.1:8000/v1/benchmark-reports/compare?baseline_path=C:\path\to\baseline.json&candidate_path=C:\path\to\candidate.json"
curl "http://127.0.0.1:8000/v1/benchmark-reports/compare-latest?results_dir=C:\path\to\benchmarks\results"
curl "http://127.0.0.1:8000/v1/benchmark-reports/trend?results_dir=C:\path\to\benchmarks\results"
curl "http://127.0.0.1:8000/v1/benchmark-reports/timeline?results_dir=C:\path\to\benchmarks\results&limit=30&offset=0"
curl "http://127.0.0.1:8000/v1/benchmark-reports/gate?results_dir=C:\path\to\benchmarks\results&require_non_regression=true&min_candidate_score=0.80"
curl "http://127.0.0.1:8000/v1/benchmark-reports/dashboard?results_dir=C:\path\to\benchmarks\results&history_limit=20&timeline_limit=30&gate_require_non_regression=true"
```

## Persistent jobs and upload storage

Asynchronous jobs are persisted in SQLite and survive service restarts.

Default storage paths:

- DB: `.ai_estimator/jobs.db`
- Uploads: `.ai_estimator/uploads/`

Environment variables:

- `AI_ESTIMATOR_DB_PATH` override SQLite path
- `AI_ESTIMATOR_UPLOAD_DIR` override uploads directory
- `AI_ESTIMATOR_JOB_WORKERS` max concurrent async job executions (default `4`, clamped `1..32`)
- `AI_ESTIMATOR_MAX_QUEUED_JOBS` optional queue backlog cap; when reached, new async submissions return `429` (unset = no cap)
- `AI_ESTIMATOR_PRUNE_ON_SUBMIT` when `true`, run terminal-job prune before async submission/rerun
- `AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS` optional age filter for auto-prune (unset = no age filter)
- `AI_ESTIMATOR_PRUNE_LIMIT` max jobs pruned per auto-prune run (default `200`, clamped `1..1000`)
- `AI_ESTIMATOR_PRUNE_CLEANUP_UPLOADS` when `true`, auto-prune also removes safe upload directories
- `AI_ESTIMATOR_API_KEY` when set, all endpoints except `/health` require header `x-api-key: <value>`
- `AI_ESTIMATOR_CLEANUP_UPLOADS` set global cleanup `true|false` for both sync/async
- `AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS` set cleanup for `/v1/analyze` uploads (default `true`)
- `AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS` set cleanup for async job uploads (default `false`)

Example (PowerShell):

```powershell
$env:AI_ESTIMATOR_DB_PATH = "C:\data\ai-estimator\jobs.db"
$env:AI_ESTIMATOR_UPLOAD_DIR = "C:\data\ai-estimator\uploads"
$env:AI_ESTIMATOR_API_KEY = "replace-with-strong-token"
$env:AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS = "true"
$env:AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS = "false"
ai-estimator-api
```

## Mobile readiness (planned)

iOS/Android apps should call the same `/v1/jobs` and `/v1/jobs/{job_id}` endpoints. For production scale:

- move job state from memory to Redis/Postgres
- move processing to worker queue (Celery/RQ/Arq)
- store PDFs/results in object storage
- add auth (JWT/OAuth)
- add tenant/project boundaries

## Current limitations

- Geometry extraction is text-driven in this MVP and requires CV/OCR modules for full plan accuracy.
- Job execution currently runs in-process in the API server; production scale should move execution to a worker queue.
- No authentication yet.

## Dependency and mirror setup

Use the helper script on Windows PowerShell:

```powershell
.\scripts\setup-dev.ps1
```

Use pinned lock files:

```powershell
.\scripts\setup-dev.ps1 -UseLockFiles
```

Point your project environment to a private mirror:

```powershell
.\scripts\setup-dev.ps1 -IndexUrl "https://packages.example.com/pypi/simple" -UseLockFiles
```

Regenerate lock files when intentionally upgrading dependencies:

```powershell
.\scripts\update-locks.ps1
```

Config templates are included in:

- `config/pip.ini.example` (Windows)
- `config/pip.conf.example` (Linux/macOS)

## Continuous integration

GitHub Actions workflow:

- `.github/workflows/ci.yml`

It runs on push and pull request, installs from lock files, performs compile checks, runs tests, and executes a CLI smoke test.
