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

The desktop app uploads PDFs to the API and shows normalized JSON output.

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

## API endpoints

- `GET /health`
- `POST /v1/analyze` synchronous analysis
- `POST /v1/jobs` async job submission
- `GET /v1/jobs/{job_id}` job status/result

## Mobile readiness (planned)

iOS/Android apps should call the same `/v1/jobs` and `/v1/jobs/{job_id}` endpoints. For production scale:

- move job state from memory to Redis/Postgres
- move processing to worker queue (Celery/RQ/Arq)
- store PDFs/results in object storage
- add auth (JWT/OAuth)
- add tenant/project boundaries

## Current limitations

- Geometry extraction is text-driven in this MVP and requires CV/OCR modules for full plan accuracy.
- In-memory job storage resets on restart.
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
