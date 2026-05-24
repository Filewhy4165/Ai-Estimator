# Architecture

## Goals

- Support all construction trades through a normalized output contract.
- Run as desktop software now.
- Scale behind internet-accessible API.
- Reuse same backend for iOS and Android later.

## Layers

1. Core engine (`ai_estimator`)
- Input normalization
- Sheet classification and trade scope resolution
- Conservative extraction modules
- Semantic model, 3D scaffold, takeoff buckets
- Cost mapping
- JSON Schema validation

2. Service layer (`service`)
- HTTP endpoints for analysis and asynchronous jobs
- File upload handling
- Job orchestration backed by SQLite persistence

3. Clients
- Desktop app (`desktop`) uses API endpoints
- Future iOS/Android clients use same API contract

## Trade scalability design

- Canonical trade enums in one place (`constants.py`)
- Sheet discipline prefix mapping + keyword model
- `analysis_mode`:
  - `selected`: user-defined subset
  - `all`: all detected trades
  - `auto`: confidence-driven subset

## Production scaling path

1. Stateless API pods
- Deploy FastAPI behind load balancer.
- Keep estimator workers external to API process.

2. Queue + workers
- API enqueues jobs and returns `job_id`.
- Workers pull jobs, process PDFs, write results.

3. Durable storage
- Object storage for uploaded PDFs and outputs.
- Postgres for job metadata and audit trails (future upgrade from SQLite).
- Redis for queue/cache (future).

4. Security and tenancy
- OAuth2/JWT authentication.
- Tenant isolation for projects and outputs.
- At-rest encryption for stored drawings.

5. Observability
- Structured logs with job IDs.
- Metrics: queue depth, processing times, failures by trade.
- Alerting on failure rate and latency.

## Mobile readiness

Keep responses stable and versioned (`/v1/...`) so React Native, Flutter, or native apps can use the same job workflow:

- Upload PDFs
- Submit analysis job
- Poll status
- Retrieve structured JSON output
