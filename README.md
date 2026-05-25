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

Default URL: `http://127.0.0.1:8000`

## Run desktop app

```bash
ai-estimator-desktop
```

The desktop app supports both synchronous analysis and async job workflows.
It also remembers your last API URL, selected PDFs, overrides file, and current job ID between launches.

Desktop async workflow:

1. Click `Choose PDFs`
2. Click `Submit Async Job`
3. Click `Refresh Job` until status is `completed` (or enable `Auto Poll Job` to refresh automatically)
4. Click `Get Review Queue` to see flagged sheets
5. Click `Export Overrides Template` to save a prefilled JSON template for sheet corrections
6. Edit the template file, then load it in `Sheet Overrides JSON` and submit a new job
7. Use `Notes` for project-specific constraints before running
8. Use `Rerun Job` to reprocess an existing job ID without re-uploading PDFs
9. Use `Export Benchmark Template` to create a prefilled benchmark manifest from a completed job
10. Use `Run Baseline Benchmark` to export a manifest and produce a scored benchmark report in one action

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
- `POST /v1/analyze` synchronous analysis
- `POST /v1/jobs` async job submission
- `POST /v1/jobs/{job_id}/rerun` async rerun using files from an existing job
- `GET /v1/jobs` list jobs (supports `limit`, `offset`, `status`)
- `GET /v1/jobs/{job_id}` job status/result
- `GET /v1/jobs/{job_id}/review-queue` prioritized review list for ambiguous sheets
- `GET /v1/jobs/{job_id}/sheet-overrides-template` prefilled override rows for unmapped/problem sheets
- `GET /v1/jobs/{job_id}/benchmark-template` prefilled benchmark manifest template from a completed job

Optional form fields for `POST /v1/analyze` and `POST /v1/jobs`:

- `sheet_overrides_json` JSON array string such as:
  `[{"source_page_index":12,"sheet_id":"A101","title":"First Floor Plan"}]`
- `notes` free-text notes/constraints (trimmed to 2000 chars)

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

Sheet overrides template endpoint query params:

- `include_all` (default `false`) include all sheets instead of only sheets needing manual correction

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

## Persistent jobs and upload storage

Asynchronous jobs are persisted in SQLite and survive service restarts.

Default storage paths:

- DB: `.ai_estimator/jobs.db`
- Uploads: `.ai_estimator/uploads/`

Environment variables:

- `AI_ESTIMATOR_DB_PATH` override SQLite path
- `AI_ESTIMATOR_UPLOAD_DIR` override uploads directory
- `AI_ESTIMATOR_CLEANUP_UPLOADS` set global cleanup `true|false` for both sync/async
- `AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS` set cleanup for `/v1/analyze` uploads (default `true`)
- `AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS` set cleanup for async job uploads (default `false`)

Example (PowerShell):

```powershell
$env:AI_ESTIMATOR_DB_PATH = "C:\data\ai-estimator\jobs.db"
$env:AI_ESTIMATOR_UPLOAD_DIR = "C:\data\ai-estimator\uploads"
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
