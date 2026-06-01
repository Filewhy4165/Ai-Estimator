from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import BoundedSemaphore, Lock, Thread
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ai_estimator.constants import DEFAULT_CSI_BY_TRADE, TRADE_NAMES
from ai_estimator.benchmark_compare import (
    build_benchmark_dashboard,
    build_benchmark_history,
    build_benchmark_score_timeline,
    build_latest_benchmark_trend_summary,
    evaluate_latest_benchmark_quality_gate,
    compare_latest_benchmark_reports as compare_latest_benchmark_reports_from_dir,
    compare_reports_from_paths,
)
from ai_estimator.pipeline import run_pipeline, sanitize_selected_trades
from ai_estimator.spec_intel import build_submittal_queries, parse_csv_tokens
from service.job_metrics import build_job_metrics_snapshot, evaluate_job_metrics_gate
from service.job_store import JobRecord, JobStore
from service.request_parsing import normalize_notes, parse_sheet_overrides_json
from service.review_queue import (
    build_benchmark_manifest_template,
    build_review_queue,
    build_sheet_overrides_template,
    build_visual_evidence,
)
from service.spec_store import SpecStore, build_spec_profile_from_file
from service.trade_coverage import build_trade_coverage_report
from service.trade_recommendation import build_trade_recommendation


def _resolve_cors_origins() -> list[str]:
    configured = os.environ.get("AI_ESTIMATOR_CORS_ORIGINS", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    return [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobCancelResponse(BaseModel):
    job_id: str
    status: str
    previous_status: str
    message: str


class JobDeleteResponse(BaseModel):
    job_id: str
    deleted: bool
    previous_status: str
    removed_upload_dirs: list[str]
    skipped_upload_dirs: list[str]


class JobPruneResponse(BaseModel):
    dry_run: bool
    statuses: list[str]
    older_than_hours: int | None
    cutoff_updated_at: str | None
    limit: int
    total_eligible: int
    total_deleted: int
    eligible_job_ids: list[str]
    deleted_job_ids: list[str]
    skipped_jobs: list[dict[str, str]]
    removed_upload_dirs: list[str]
    skipped_upload_dirs: list[str]


class TradeCatalogItem(BaseModel):
    trade: str
    label: str
    csi_codes: list[str]


class TradeCatalogResponse(BaseModel):
    analysis_modes: list[str]
    trades: list[TradeCatalogItem]


class SpecProfileResponse(BaseModel):
    spec_id: str
    tenant_id: str = "public"
    title: str
    organization: str
    agency: str
    standard_name: str
    project_type: str
    tags: list[str]
    is_public: bool
    source_file_name: str
    source_file_path: str
    notes: str
    detected_standard_refs: list[str]
    detected_trade_hints: list[str]
    text_excerpt: str
    created_at: str
    updated_at: str


class SpecCatalogResponse(BaseModel):
    items: list[SpecProfileResponse]
    total_available: int
    total_returned: int
    limit: int
    offset: int


class SpecOrganizationResponse(BaseModel):
    organizations: list[str]


class SpecUploadResponse(BaseModel):
    item: SpecProfileResponse


class SpecSubmittalSearchResponse(BaseModel):
    query_count: int
    queries: list[str]
    web_lookup_enabled: bool
    source_profiles: list[str]
    items: list[dict[str, Any]]
    warnings: list[str]


class JobListResponse(BaseModel):
    items: list[JobRecord]
    total_returned: int
    limit: int
    offset: int


class JobMetricsResponse(BaseModel):
    generated_at: str
    window_requested: int
    window_applied: int
    jobs_considered: int
    status_counts: dict[str, int]
    active_jobs: int
    terminal_jobs: int
    failure_rate: float | None
    throughput_last_24h: dict[str, float | int | None]
    queue_wait_seconds: dict[str, float | int | None]
    run_duration_seconds: dict[str, float | int | None]
    result_sheet_count: dict[str, float | int | None]
    result_issue_count: dict[str, float | int | None]
    quality: dict[str, float | int | None]


class JobMetricsGateResponse(BaseModel):
    passed: bool
    thresholds: dict[str, float | int | None]
    actual: dict[str, float | int | None]
    failures: list[dict[str, Any]]
    snapshot: dict[str, Any]


class JobCapacityResponse(BaseModel):
    worker_limit: int
    running_jobs: int
    queued_jobs: int
    running_slots_available: int
    max_queued_jobs: int | None
    queue_capacity_remaining: int | None


_TERMINAL_JOB_STATUSES = {"completed", "failed", "canceled"}
_ACTIVE_JOB_STATUSES = {"queued", "running"}
_LISTABLE_JOB_STATUSES = _ACTIVE_JOB_STATUSES | _TERMINAL_JOB_STATUSES
_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
_DEFAULT_TENANT_ID = "default"
_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class TradeRecommendationResponse(BaseModel):
    job_id: str
    requested_mode: str
    requested_trades: list[str]
    detected_trades: list[str]
    recommended_mode: str
    recommended_trades: list[str]
    confidence: float
    needs_user_review: bool
    decision_rationale: list[str]
    trade_scores: list[dict[str, Any]]


class TradeCoverageResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    needs_review_trades: list[str]
    trades: list[dict[str, Any]]


class JobReadinessReportResponse(BaseModel):
    job_id: str
    generated_at: str
    review_queue_summary: dict[str, Any]
    trade_recommendation: dict[str, Any]
    trade_coverage: dict[str, Any]
    ops_gate: dict[str, Any]
    handoff_recommendation: dict[str, Any]


class JobRerunRecommendationResponse(JobCreateResponse):
    source_job_id: str
    recommended_mode: str
    recommended_trades: list[str]
    recommendation_confidence: float | None


class ReviewQueueResponse(BaseModel):
    job_id: str
    low_confidence_threshold: float
    summary: dict[str, Any]
    items: list[dict[str, Any]]


class SheetOverridesTemplateResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    items: list[dict[str, Any]]


class BenchmarkTemplateResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    manifest: dict[str, Any]


class BenchmarkHistoryResponse(BaseModel):
    results_dir: str
    total_available: int
    total_returned: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class BenchmarkTrendResponse(BaseModel):
    results_dir: str
    total_available: int
    trend: str | None
    overall_score_delta: float | None
    comparison_mode: str
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    metric_count: int


class BenchmarkTimelineResponse(BaseModel):
    results_dir: str
    total_available: int
    total_returned: int
    limit: int
    offset: int
    points: list[dict[str, Any]]


class BenchmarkGateResponse(BaseModel):
    results_dir: str
    total_available: int
    passed: bool
    thresholds: dict[str, Any]
    actual: dict[str, Any]
    failures: list[dict[str, Any]]


class BenchmarkDashboardResponse(BaseModel):
    results_dir: str
    total_available: int
    history: dict[str, Any]
    timeline: dict[str, Any]
    trend: dict[str, Any] | None
    gate: dict[str, Any] | None
    warnings: list[str]


app = FastAPI(title="AI Estimator Service", version="0.1.0")
_cors_origins = _resolve_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_job_store: JobStore | None = None
_spec_store: SpecStore | None = None
_upload_root: Path | None = None
_resource_lock = Lock()
_job_run_semaphore: BoundedSemaphore | None = None
_job_run_semaphore_limit: int | None = None


@app.middleware("http")
async def require_api_key_when_configured(request: Request, call_next):  # type: ignore[no-untyped-def]
    expected = os.environ.get("AI_ESTIMATOR_API_KEY", "").strip()
    if not expected:
        return await call_next(request)
    if request.url.path == "/health":
        return await call_next(request)
    provided = str(request.headers.get("x-api-key", "")).strip()
    if not _is_api_key_authorized(expected=expected, provided=provided):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key."},
        )
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db_path": _get_job_store().db_path}


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Estimator Service</title>
  <style>
    body {
      margin: 0;
      font-family: Segoe UI, Arial, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
    }
    main {
      max-width: 760px;
      margin: 48px auto;
      padding: 24px;
      background: #111827;
      border: 1px solid #1f2937;
      border-radius: 12px;
    }
    h1 { margin-top: 0; }
    p { color: #cbd5e1; }
    ul { padding-left: 20px; }
    a { color: #93c5fd; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code {
      background: #0b1220;
      border: 1px solid #1f2937;
      border-radius: 6px;
      padding: 2px 6px;
    }
  </style>
</head>
<body>
  <main>
    <h1>AI Estimator Service</h1>
    <p>Service is running. Use the links below.</p>
    <ul>
      <li><a href="/docs">API docs</a></li>
      <li><a href="/health">Health check</a></li>
      <li><a href="/v1/jobs">Jobs list</a></li>
      <li><a href="/v1/meta/trades">Trade catalog</a></li>
      <li><a href="/v1/specs/catalog">Specs catalog</a></li>
    </ul>
    <p>For async analysis, submit to <code>/v1/jobs</code>.</p>
  </main>
</body>
</html>
"""


@app.get("/v1/meta/trades", response_model=TradeCatalogResponse)
def get_trade_catalog() -> TradeCatalogResponse:
    return TradeCatalogResponse(
        analysis_modes=["auto", "selected", "all"],
        trades=[
            TradeCatalogItem(
                trade=trade,
                label=_format_trade_label(trade),
                csi_codes=list(DEFAULT_CSI_BY_TRADE.get(trade, [])),
            )
            for trade in TRADE_NAMES
        ],
    )


@app.get("/v1/specs/catalog", response_model=SpecCatalogResponse)
def get_specs_catalog(
    organization: str = "",
    agency: str = "",
    public_only: bool = True,
    project_type: str = "",
    limit: int = 100,
    offset: int = 0,
    request: Request = None,
) -> SpecCatalogResponse:
    tenant_id = _tenant_id_for_request(request)
    items, total = _get_spec_store().list_specs(
        organization=organization,
        agency=agency,
        public_only=public_only,
        project_type=project_type,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )
    return SpecCatalogResponse(
        items=[SpecProfileResponse(**_normalize_spec_item(item)) for item in items],
        total_available=total,
        total_returned=len(items),
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


@app.get("/v1/specs/organizations", response_model=SpecOrganizationResponse)
def get_specs_organizations(request: Request = None) -> SpecOrganizationResponse:
    tenant_id = _tenant_id_for_request(request)
    return SpecOrganizationResponse(organizations=_get_spec_store().list_organizations(tenant_id=tenant_id))


@app.get("/v1/specs/{spec_id}", response_model=SpecProfileResponse)
def get_spec_profile(spec_id: str, request: Request = None) -> SpecProfileResponse:
    tenant_id = _tenant_id_for_request(request)
    item = _get_spec_store().get_spec(spec_id, tenant_id=tenant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Spec profile not found")
    return SpecProfileResponse(**_normalize_spec_item(item))


@app.post("/v1/specs/upload", response_model=SpecUploadResponse)
async def upload_spec_profile(
    spec_file: UploadFile = File(...),
    organization: str = Form(...),
    agency: str = Form(""),
    title: str = Form(""),
    standard_name: str = Form(""),
    project_type: str = Form(""),
    tags_csv: str = Form(""),
    is_public: bool = Form(False),
    notes: str = Form(""),
    request: Request = None,
) -> SpecUploadResponse:
    tenant_id = _tenant_id_for_request(request)
    organization_clean = organization.strip()
    if not organization_clean:
        raise HTTPException(status_code=400, detail="organization is required.")
    upload_dir = _get_upload_root() / "specs" / str(uuid.uuid4())
    saved = await _save_uploads(
        [spec_file],
        upload_dir,
        allowed_suffixes={".pdf", ".txt", ".md", ".csv", ".json"},
    )
    if not saved:
        raise HTTPException(status_code=400, detail="No spec file uploaded.")
    saved_path = saved[0]
    tags = parse_csv_tokens(tags_csv)
    profile = build_spec_profile_from_file(
        file_path=saved_path,
        title=title.strip() or Path(saved_path).stem,
        organization=organization_clean,
        agency=agency.strip() or organization_clean,
        standard_name=standard_name.strip(),
        project_type=project_type.strip(),
        tags=tags,
        notes=notes.strip(),
        is_public=bool(is_public),
        tenant_id=tenant_id,
    )
    stored = _get_spec_store().upsert_spec(profile)
    return SpecUploadResponse(item=SpecProfileResponse(**_normalize_spec_item(stored)))


@app.get("/v1/specs/submittals/search", response_model=SpecSubmittalSearchResponse)
def search_spec_submittals(
    spec_profile_ids: str = "",
    max_results: int = 10,
    request: Request = None,
) -> SpecSubmittalSearchResponse:
    tenant_id = _tenant_id_for_request(request)
    spec_ids = parse_csv_tokens(spec_profile_ids)
    selected_profiles = _get_spec_store().get_by_ids(spec_ids, tenant_id=tenant_id)
    queries = build_submittal_queries(spec_profiles=selected_profiles, max_queries=40)
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    web_enabled = _resolve_web_submittal_lookup_enabled()

    if not selected_profiles:
        warnings.append("No spec profiles matched the provided spec_profile_ids.")
    if not queries:
        warnings.append("No submittal search queries could be generated from selected specs.")

    if web_enabled and queries:
        for query in queries[: max(1, min(max_results, 25))]:
            items.extend(_search_public_product_docs(query=query, limit=2))
    elif queries:
        warnings.append(
            "Web lookup is disabled. Set AI_ESTIMATOR_ENABLE_WEB_SUBMITTALS=true to fetch live links."
        )

    deduped: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for item in items:
        link = str(item.get("url", "")).strip().lower()
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        deduped.append(item)

    return SpecSubmittalSearchResponse(
        query_count=len(queries),
        queries=queries,
        web_lookup_enabled=web_enabled,
        source_profiles=[str(item.get("spec_id", "")).strip() for item in selected_profiles],
        items=deduped[: max(1, min(max_results, 100))],
        warnings=warnings,
    )


@app.post("/v1/analyze")
async def analyze(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
    sheet_overrides_json: str | None = Form(None),
    spec_profile_ids: str = Form(""),
    spec_organization: str = Form(""),
    include_public_specs: bool = Form(False),
    notes: str | None = Form(None),
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = _tenant_id_for_request(request)
    selected_trade_list = sanitize_selected_trades(selected_trades)
    try:
        _validate_analysis_scope(analysis_mode=analysis_mode, selected_trades=selected_trade_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request_id = str(uuid.uuid4())
    request_dir = _get_upload_root() / "sync" / request_id
    pdf_paths = await _save_uploads(files, request_dir, allowed_suffixes={".pdf"})
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        sheet_overrides = parse_sheet_overrides_json(sheet_overrides_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved_spec_profiles = _resolve_spec_profiles_for_request(
        spec_profile_ids_csv=spec_profile_ids,
        spec_organization=spec_organization,
        include_public_specs=include_public_specs,
        tenant_id=tenant_id,
    )
    normalized_notes = normalize_notes(notes)

    try:
        payload = run_pipeline(
            pdf_paths=pdf_paths,
            analysis_mode=analysis_mode,
            selected_trades=selected_trade_list,
            sheet_overrides=sheet_overrides,
            spec_profiles=resolved_spec_profiles,
            notes=normalized_notes,
            validate_schema=True,
        )
        return payload
    finally:
        if _should_cleanup_uploads(mode="sync"):
            shutil.rmtree(request_dir, ignore_errors=True)


@app.post("/v1/jobs", status_code=202, response_model=JobCreateResponse)
async def create_job(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
    sheet_overrides_json: str | None = Form(None),
    spec_profile_ids: str = Form(""),
    spec_organization: str = Form(""),
    include_public_specs: bool = Form(False),
    notes: str | None = Form(None),
    request: Request = None,
) -> JobCreateResponse:
    tenant_id = _tenant_id_for_request(request)
    selected_trade_list = sanitize_selected_trades(selected_trades)
    try:
        _validate_analysis_scope(analysis_mode=analysis_mode, selected_trades=selected_trade_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _maybe_auto_prune_jobs(tenant_id=tenant_id)
    _enforce_queued_job_limit(tenant_id=tenant_id)

    job_id = str(uuid.uuid4())
    job_upload_dir = _get_upload_root() / "jobs" / job_id
    pdf_paths = await _save_uploads(files, job_upload_dir, allowed_suffixes={".pdf"})
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        sheet_overrides = parse_sheet_overrides_json(sheet_overrides_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved_spec_profiles = _resolve_spec_profiles_for_request(
        spec_profile_ids_csv=spec_profile_ids,
        spec_organization=spec_organization,
        include_public_specs=include_public_specs,
        tenant_id=tenant_id,
    )
    normalized_notes = normalize_notes(notes)

    now = _utc_now()
    record = JobRecord(
        job_id=job_id,
        tenant_id=tenant_id,
        status="queued",
        created_at=now,
        updated_at=now,
        input={
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trade_list,
            "sheet_overrides": sheet_overrides or [],
            "spec_profile_ids": [str(item.get("spec_id", "")).strip() for item in resolved_spec_profiles],
            "spec_organization": spec_organization.strip(),
            "include_public_specs": bool(include_public_specs),
            "notes": normalized_notes,
            "tenant_id": tenant_id,
            "uploaded_files": [
                {
                    "file_name": Path(path).name,
                    "path": str(path),
                }
                for path in pdf_paths
            ],
        },
    )
    _get_job_store().create_job(record)

    thread = Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "pdf_paths": pdf_paths,
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trade_list,
            "sheet_overrides": sheet_overrides,
            "spec_profiles": resolved_spec_profiles,
            "notes": normalized_notes,
            "upload_dir": str(job_upload_dir),
            "tenant_id": tenant_id,
        },
        daemon=True,
    )
    thread.start()
    return JobCreateResponse(job_id=job_id, status="queued")


@app.post("/v1/jobs/{job_id}/rerun", status_code=202, response_model=JobCreateResponse)
async def rerun_job(
    job_id: str,
    analysis_mode: str | None = Form(None),
    selected_trades: str | None = Form(None),
    sheet_overrides_json: str | None = Form(None),
    spec_profile_ids: str | None = Form(None),
    spec_organization: str | None = Form(None),
    include_public_specs: bool | None = Form(None),
    notes: str | None = Form(None),
    request: Request = None,
) -> JobCreateResponse:
    tenant_id = _tenant_id_for_request(request)
    _maybe_auto_prune_jobs(tenant_id=tenant_id)
    _enforce_queued_job_limit(tenant_id=tenant_id)
    source_record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not source_record:
        raise HTTPException(status_code=404, detail="Job not found")

    source_input = source_record.input if isinstance(source_record.input, dict) else {}
    try:
        (
            resolved_mode,
            resolved_trades,
            resolved_overrides,
            resolved_spec_profiles,
            resolved_spec_organization,
            resolved_include_public_specs,
            resolved_notes,
        ) = _resolve_rerun_inputs(
            source_input=source_input,
            tenant_id=tenant_id,
            analysis_mode=analysis_mode,
            selected_trades=selected_trades,
            sheet_overrides_json=sheet_overrides_json,
            spec_profile_ids=spec_profile_ids,
            spec_organization=spec_organization,
            include_public_specs=include_public_specs,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pdf_paths, missing_paths = _resolve_uploaded_pdf_paths(source_input)
    if not pdf_paths:
        raise HTTPException(
            status_code=409,
            detail=(
                "No reusable uploaded files were found for this job. "
                "Submit a new job with files, or disable async upload cleanup."
            ),
        )
    if missing_paths:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Some uploaded files from the source job are missing. "
                    "Disable async upload cleanup or submit a new job with files."
                ),
                "missing_paths": missing_paths[:20],
            },
        )

    rerun_job_id = _queue_rerun_job(
        source_job_id=job_id,
        tenant_id=tenant_id,
        pdf_paths=pdf_paths,
        analysis_mode=resolved_mode,
        selected_trades=resolved_trades,
        sheet_overrides=resolved_overrides,
        spec_profiles=resolved_spec_profiles,
        notes=resolved_notes,
        extra_input={
            "spec_profile_ids": [
                str(item.get("spec_id", "")).strip() for item in resolved_spec_profiles
            ],
            "spec_organization": resolved_spec_organization,
            "include_public_specs": resolved_include_public_specs,
        },
    )
    return JobCreateResponse(job_id=rerun_job_id, status="queued")


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobCancelResponse)
def cancel_job(
    job_id: str,
    request: Request = None,
) -> JobCancelResponse:
    tenant_id = _tenant_id_for_request(request)
    store = _get_job_store()
    record = store.get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = str(record.status).strip().lower()
    if current_status == "canceled":
        return JobCancelResponse(
            job_id=job_id,
            status="canceled",
            previous_status="canceled",
            message="Job is already canceled.",
        )
    if current_status in {"completed", "failed"}:
        raise HTTPException(
            status_code=409,
            detail=f"Job is already terminal ({current_status}) and cannot be canceled.",
        )

    now = _utc_now()
    if current_status == "queued":
        updated = store.transition_job_if_current(
            job_id,
            current_status="queued",
            status="canceled",
            updated_at=now,
            completed_at=now,
            error="Job canceled by user before execution.",
            tenant_id=tenant_id,
        )
        message = "Queued job canceled."
    elif current_status == "running":
        updated = store.transition_job_if_current(
            job_id,
            current_status="running",
            status="canceled",
            updated_at=now,
            completed_at=now,
            error=(
                "Job canceled by user while running. "
                "Worker completion updates will be ignored."
            ),
            tenant_id=tenant_id,
        )
        message = "Running job marked canceled."
    else:
        raise HTTPException(
            status_code=409,
            detail=f"Job status '{current_status}' does not support cancellation.",
        )

    if updated:
        return JobCancelResponse(
            job_id=job_id,
            status="canceled",
            previous_status=current_status,
            message=message,
        )

    latest = store.get_job(job_id, tenant_id=tenant_id)
    latest_status = str(latest.status).strip().lower() if latest else "unknown"
    if latest_status == "canceled":
        return JobCancelResponse(
            job_id=job_id,
            status="canceled",
            previous_status=current_status,
            message="Job is already canceled.",
        )
    if latest_status in {"completed", "failed"}:
        raise HTTPException(
            status_code=409,
            detail=f"Job reached terminal state '{latest_status}' before cancellation applied.",
        )
    raise HTTPException(
        status_code=409,
        detail=f"Job status changed to '{latest_status}' before cancellation could be applied.",
    )


@app.delete("/v1/jobs/{job_id}", response_model=JobDeleteResponse)
def delete_job(
    job_id: str,
    cleanup_uploads: bool = False,
    request: Request = None,
) -> JobDeleteResponse:
    tenant_id = _tenant_id_for_request(request)
    store = _get_job_store()
    record = store.get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = str(record.status).strip().lower()
    if current_status in _ACTIVE_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete active job with status '{current_status}'. "
                "Cancel or wait for completion first."
            ),
        )

    removed_dirs: list[str] = []
    skipped_dirs: list[str] = []
    if cleanup_uploads:
        removed_dirs, skipped_dirs = _cleanup_upload_dirs_for_job(record)

    deleted = store.delete_job(job_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Job changed before deletion could be applied.",
        )

    return JobDeleteResponse(
        job_id=job_id,
        deleted=True,
        previous_status=current_status,
        removed_upload_dirs=removed_dirs,
        skipped_upload_dirs=skipped_dirs,
    )


@app.post("/v1/jobs/prune", response_model=JobPruneResponse)
def prune_jobs(
    statuses: str = "completed,failed,canceled",
    older_than_hours: int | None = None,
    limit: int = 100,
    dry_run: bool = True,
    cleanup_uploads: bool = False,
    tenant_id: str | None = None,
    request: Request = None,
) -> JobPruneResponse:
    resolved_tenant_id = _tenant_id_for_request(request, explicit_tenant_id=tenant_id)
    status_tokens = _parse_prune_statuses_csv(statuses)
    if older_than_hours is not None and older_than_hours < 1:
        raise HTTPException(status_code=400, detail="older_than_hours must be at least 1 when provided.")

    cutoff_updated_at: str | None = None
    if older_than_hours is not None:
        cutoff_updated_at = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()

    limit_applied = max(1, min(limit, 1000))
    store = _get_job_store()
    candidates = store.list_jobs_for_prune(
        statuses=status_tokens,
        updated_before=cutoff_updated_at,
        limit=limit_applied,
        tenant_id=resolved_tenant_id,
    )
    eligible_job_ids = [record.job_id for record in candidates]
    if dry_run:
        return JobPruneResponse(
            dry_run=True,
            statuses=status_tokens,
            older_than_hours=older_than_hours,
            cutoff_updated_at=cutoff_updated_at,
            limit=limit_applied,
            total_eligible=len(eligible_job_ids),
            total_deleted=0,
            eligible_job_ids=eligible_job_ids,
            deleted_job_ids=[],
            skipped_jobs=[],
            removed_upload_dirs=[],
            skipped_upload_dirs=[],
        )

    deleted_job_ids: list[str] = []
    skipped_jobs: list[dict[str, str]] = []
    removed_upload_dirs: list[str] = []
    skipped_upload_dirs: list[str] = []
    removed_seen: set[str] = set()
    skipped_seen: set[str] = set()

    for candidate in candidates:
        latest = store.get_job(candidate.job_id, tenant_id=resolved_tenant_id)
        if not latest:
            skipped_jobs.append({"job_id": candidate.job_id, "reason": "Job not found during prune."})
            continue
        latest_status = str(latest.status).strip().lower()
        if latest_status not in _TERMINAL_JOB_STATUSES:
            skipped_jobs.append(
                {
                    "job_id": latest.job_id,
                    "reason": f"Status changed to active state '{latest_status}'.",
                }
            )
            continue

        if cleanup_uploads:
            removed_batch, skipped_batch = _cleanup_upload_dirs_for_job(latest)
            for path in removed_batch:
                key = path.lower()
                if key in removed_seen:
                    continue
                removed_seen.add(key)
                removed_upload_dirs.append(path)
            for path in skipped_batch:
                key = path.lower()
                if key in skipped_seen:
                    continue
                skipped_seen.add(key)
                skipped_upload_dirs.append(path)

        deleted = store.delete_job(latest.job_id, tenant_id=resolved_tenant_id)
        if deleted:
            deleted_job_ids.append(latest.job_id)
        else:
            skipped_jobs.append({"job_id": latest.job_id, "reason": "Delete operation was not applied."})

    return JobPruneResponse(
        dry_run=False,
        statuses=status_tokens,
        older_than_hours=older_than_hours,
        cutoff_updated_at=cutoff_updated_at,
        limit=limit_applied,
        total_eligible=len(eligible_job_ids),
        total_deleted=len(deleted_job_ids),
        eligible_job_ids=eligible_job_ids,
        deleted_job_ids=deleted_job_ids,
        skipped_jobs=skipped_jobs,
        removed_upload_dirs=removed_upload_dirs,
        skipped_upload_dirs=skipped_upload_dirs,
    )


@app.post(
    "/v1/jobs/{job_id}/rerun-recommended",
    status_code=202,
    response_model=JobRerunRecommendationResponse,
)
def rerun_job_with_recommendation(
    job_id: str,
    request: Request = None,
) -> JobRerunRecommendationResponse:
    tenant_id = _tenant_id_for_request(request)
    _maybe_auto_prune_jobs(tenant_id=tenant_id)
    _enforce_queued_job_limit(tenant_id=tenant_id)
    source_record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not source_record:
        raise HTTPException(status_code=404, detail="Job not found")

    source_input = source_record.input if isinstance(source_record.input, dict) else {}
    pdf_paths, missing_paths = _resolve_uploaded_pdf_paths(source_input)
    if not pdf_paths:
        raise HTTPException(
            status_code=409,
            detail=(
                "No reusable uploaded files were found for this job. "
                "Submit a new job with files, or disable async upload cleanup."
            ),
        )
    if missing_paths:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Some uploaded files from the source job are missing. "
                    "Disable async upload cleanup or submit a new job with files."
                ),
                "missing_paths": missing_paths[:20],
            },
        )

    recommendation = build_trade_recommendation(
        job_id=job_id,
        result=source_record.result if isinstance(source_record.result, dict) else None,
    )
    recommended_mode = str(recommendation.get("recommended_mode", "all")).strip().lower()
    if recommended_mode not in {"selected", "all"}:
        recommended_mode = "all"
    recommended_trades_raw = recommendation.get("recommended_trades", [])
    recommended_trades = (
        [str(trade).strip() for trade in recommended_trades_raw if str(trade).strip()]
        if isinstance(recommended_trades_raw, list)
        else []
    )
    if recommended_mode != "selected":
        recommended_trades = []

    resolved_notes = normalize_notes(
        _append_note(
            source_notes=source_input.get("notes") if isinstance(source_input.get("notes"), str) else None,
            marker=(
                "Auto rerun using trade recommendation: "
                f"mode={recommended_mode}, confidence={recommendation.get('confidence')}."
            ),
        )
    )
    resolved_overrides = _normalize_sheet_overrides_from_input(source_input.get("sheet_overrides"))
    resolved_spec_profiles = _resolve_spec_profiles_for_request(
        spec_profile_ids_csv=",".join(
            str(token).strip() for token in source_input.get("spec_profile_ids", []) if str(token).strip()
        ),
        spec_organization=str(source_input.get("spec_organization", "")).strip(),
        include_public_specs=bool(source_input.get("include_public_specs", False)),
        tenant_id=tenant_id,
    )

    rerun_job_id = _queue_rerun_job(
        source_job_id=job_id,
        tenant_id=tenant_id,
        pdf_paths=pdf_paths,
        analysis_mode=recommended_mode,
        selected_trades=recommended_trades,
        sheet_overrides=resolved_overrides,
        spec_profiles=resolved_spec_profiles,
        notes=resolved_notes,
        extra_input={
            "trade_recommendation": {
                "recommended_mode": recommended_mode,
                "recommended_trades": recommended_trades,
                "confidence": recommendation.get("confidence"),
            },
            "spec_profile_ids": [str(item.get("spec_id", "")).strip() for item in resolved_spec_profiles],
            "spec_organization": str(source_input.get("spec_organization", "")).strip(),
            "include_public_specs": bool(source_input.get("include_public_specs", False)),
        },
    )
    confidence_raw = recommendation.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
    return JobRerunRecommendationResponse(
        job_id=rerun_job_id,
        status="queued",
        source_job_id=job_id,
        recommended_mode=recommended_mode,
        recommended_trades=recommended_trades,
        recommendation_confidence=confidence,
    )


@app.get("/v1/jobs/metrics", response_model=JobMetricsResponse)
def get_job_metrics(
    window: int = 200,
    request: Request = None,
) -> JobMetricsResponse:
    tenant_id = _tenant_id_for_request(request)
    window_applied = max(1, min(window, 5000))
    records = _get_job_store().list_recent_jobs(limit=window_applied, tenant_id=tenant_id)
    payload = build_job_metrics_snapshot(
        records,
        window_requested=window,
        window_applied=window_applied,
        generated_at=_utc_now(),
    )
    return JobMetricsResponse(**payload)


@app.get("/v1/jobs/metrics/gate", response_model=JobMetricsGateResponse)
def get_job_metrics_gate(
    window: int = 200,
    max_failure_rate: float | None = None,
    max_active_jobs: int | None = None,
    max_missing_scale_rate: float | None = None,
    max_unmapped_sheet_rate: float | None = None,
    min_jobs_per_hour_24h: float | None = None,
    request: Request = None,
) -> JobMetricsGateResponse:
    tenant_id = _tenant_id_for_request(request)
    window_applied = max(1, min(window, 5000))
    records = _get_job_store().list_recent_jobs(limit=window_applied, tenant_id=tenant_id)
    snapshot = build_job_metrics_snapshot(
        records,
        window_requested=window,
        window_applied=window_applied,
        generated_at=_utc_now(),
    )
    payload = evaluate_job_metrics_gate(
        snapshot,
        max_failure_rate=max_failure_rate,
        max_active_jobs=max_active_jobs,
        max_missing_scale_rate=max_missing_scale_rate,
        max_unmapped_sheet_rate=max_unmapped_sheet_rate,
        min_jobs_per_hour_24h=min_jobs_per_hour_24h,
    )
    return JobMetricsGateResponse(**payload)


@app.get("/v1/jobs/capacity", response_model=JobCapacityResponse)
def get_job_capacity(
    request: Request = None,
) -> JobCapacityResponse:
    tenant_id = _tenant_id_for_request(request)
    store = _get_job_store()
    worker_limit = _resolve_job_worker_limit()
    running_jobs = store.count_jobs(status="running", tenant_id=tenant_id)
    queued_jobs = store.count_jobs(status="queued", tenant_id=tenant_id)
    max_queued_jobs = _resolve_max_queued_jobs()
    queue_capacity_remaining = (
        max(0, max_queued_jobs - queued_jobs) if max_queued_jobs is not None else None
    )
    return JobCapacityResponse(
        worker_limit=worker_limit,
        running_jobs=running_jobs,
        queued_jobs=queued_jobs,
        running_slots_available=max(0, worker_limit - running_jobs),
        max_queued_jobs=max_queued_jobs,
        queue_capacity_remaining=queue_capacity_remaining,
    )


@app.get("/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return record.model_dump()


@app.get("/v1/jobs/{job_id}/review-queue", response_model=ReviewQueueResponse)
def get_job_review_queue(
    job_id: str,
    low_confidence_threshold: float = 0.75,
    include_only_flagged: bool = True,
    request: Request = None,
) -> ReviewQueueResponse:
    if low_confidence_threshold < 0 or low_confidence_threshold > 1:
        raise HTTPException(status_code=400, detail="low_confidence_threshold must be between 0 and 1.")
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_review_queue(
        job_id=job_id,
        result=record.result,
        low_confidence_threshold=low_confidence_threshold,
        include_only_flagged=include_only_flagged,
    )
    return ReviewQueueResponse(**payload)


@app.get("/v1/jobs/{job_id}/sheet-overrides-template", response_model=SheetOverridesTemplateResponse)
def get_sheet_overrides_template(
    job_id: str,
    include_all: bool = False,
    request: Request = None,
) -> SheetOverridesTemplateResponse:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_sheet_overrides_template(
        job_id=job_id,
        result=record.result,
        include_all=include_all,
    )
    return SheetOverridesTemplateResponse(**payload)


@app.get("/v1/jobs/{job_id}/visual-evidence")
def get_job_visual_evidence(
    job_id: str,
    limit: int = 250,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_visual_evidence(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
        limit=limit,
    )


@app.get("/v1/jobs/{job_id}/trade-recommendation", response_model=TradeRecommendationResponse)
def get_trade_recommendation(
    job_id: str,
    request: Request = None,
) -> TradeRecommendationResponse:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_trade_recommendation(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return TradeRecommendationResponse(**payload)


@app.get("/v1/jobs/{job_id}/trade-coverage", response_model=TradeCoverageResponse)
def get_trade_coverage(
    job_id: str,
    request: Request = None,
) -> TradeCoverageResponse:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_trade_coverage_report(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return TradeCoverageResponse(**payload)


@app.get("/v1/jobs/{job_id}/readiness-report", response_model=JobReadinessReportResponse)
def get_job_readiness_report(
    job_id: str,
    request: Request = None,
) -> JobReadinessReportResponse:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    result_payload = record.result if isinstance(record.result, dict) else None
    review_queue = build_review_queue(
        job_id=job_id,
        result=result_payload,
        low_confidence_threshold=0.75,
        include_only_flagged=True,
    )
    trade_recommendation = build_trade_recommendation(job_id=job_id, result=result_payload)
    trade_coverage = build_trade_coverage_report(job_id=job_id, result=result_payload)

    recent_records = _get_job_store().list_recent_jobs(limit=500, tenant_id=tenant_id)
    snapshot = build_job_metrics_snapshot(
        recent_records,
        window_requested=500,
        window_applied=500,
        generated_at=_utc_now(),
    )
    ops_gate = evaluate_job_metrics_gate(
        snapshot,
        max_failure_rate=0.2,
        max_active_jobs=25,
        max_missing_scale_rate=0.4,
        max_unmapped_sheet_rate=0.25,
        min_jobs_per_hour_24h=0.05,
    )
    handoff = _build_handoff_recommendation(
        review_queue_summary=review_queue.get("summary", {}),
        trade_recommendation=trade_recommendation,
        trade_coverage=trade_coverage,
        ops_gate=ops_gate,
    )

    return JobReadinessReportResponse(
        job_id=job_id,
        generated_at=_utc_now(),
        review_queue_summary=review_queue.get("summary", {}),
        trade_recommendation=trade_recommendation,
        trade_coverage=trade_coverage,
        ops_gate=ops_gate,
        handoff_recommendation=handoff,
    )


@app.get("/v1/jobs/{job_id}/benchmark-template", response_model=BenchmarkTemplateResponse)
def get_benchmark_template(
    job_id: str,
    include_unmapped: bool = False,
    case_id: str | None = None,
    request: Request = None,
) -> BenchmarkTemplateResponse:
    tenant_id = _tenant_id_for_request(request)
    record = _get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_benchmark_manifest_template(
        job_id=job_id,
        result=record.result,
        job_input=record.input if isinstance(record.input, dict) else {},
        include_unmapped=include_unmapped,
        case_id=case_id,
    )
    return BenchmarkTemplateResponse(**payload)


@app.get("/v1/benchmark-reports/compare")
def compare_benchmark_reports_endpoint(
    baseline_path: str,
    candidate_path: str,
) -> dict[str, Any]:
    baseline = _resolve_benchmark_report_path(baseline_path, label="Baseline")
    candidate = _resolve_benchmark_report_path(candidate_path, label="Candidate")
    if not baseline.exists():
        raise HTTPException(status_code=404, detail=f"Baseline report not found: {baseline}")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Candidate report not found: {candidate}")

    try:
        return compare_reports_from_paths(baseline, candidate)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/benchmark-reports/compare-latest")
def compare_latest_benchmark_reports_endpoint(
    results_dir: str = "",
) -> dict[str, Any]:
    target_dir = _resolve_benchmark_results_dir(results_dir)

    try:
        return compare_latest_benchmark_reports_from_dir(target_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/benchmark-reports/history", response_model=BenchmarkHistoryResponse)
def get_benchmark_reports_history(
    results_dir: str = "",
    limit: int = 50,
    offset: int = 0,
) -> BenchmarkHistoryResponse:
    target_dir = _resolve_benchmark_results_dir(results_dir)

    payload = build_benchmark_history(results_dir=target_dir, limit=limit, offset=offset)
    return BenchmarkHistoryResponse(**payload)


@app.get("/v1/benchmark-reports/trend", response_model=BenchmarkTrendResponse)
def get_benchmark_reports_trend(
    results_dir: str = "",
) -> BenchmarkTrendResponse:
    target_dir = _resolve_benchmark_results_dir(results_dir)

    try:
        payload = build_latest_benchmark_trend_summary(target_dir)
        return BenchmarkTrendResponse(**payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/benchmark-reports/gate", response_model=BenchmarkGateResponse)
def get_benchmark_reports_gate(
    results_dir: str = "",
    min_candidate_score: float | None = None,
    max_negative_delta: float | None = None,
    require_non_regression: bool = True,
    require_improvement: bool = False,
) -> BenchmarkGateResponse:
    target_dir = _resolve_benchmark_results_dir(results_dir)

    try:
        payload = evaluate_latest_benchmark_quality_gate(
            target_dir,
            min_candidate_score=min_candidate_score,
            max_negative_delta=max_negative_delta,
            require_non_regression=require_non_regression,
            require_improvement=require_improvement,
        )
        return BenchmarkGateResponse(**payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/benchmark-reports/timeline", response_model=BenchmarkTimelineResponse)
def get_benchmark_reports_timeline(
    results_dir: str = "",
    limit: int = 30,
    offset: int = 0,
) -> BenchmarkTimelineResponse:
    target_dir = _resolve_benchmark_results_dir(results_dir)

    payload = build_benchmark_score_timeline(results_dir=target_dir, limit=limit, offset=offset)
    return BenchmarkTimelineResponse(**payload)


@app.get("/v1/benchmark-reports/dashboard", response_model=BenchmarkDashboardResponse)
def get_benchmark_reports_dashboard(
    results_dir: str = "",
    history_limit: int = 20,
    history_offset: int = 0,
    timeline_limit: int = 30,
    timeline_offset: int = 0,
    gate_min_candidate_score: float | None = None,
    gate_max_negative_delta: float | None = None,
    gate_require_non_regression: bool = True,
    gate_require_improvement: bool = False,
) -> BenchmarkDashboardResponse:
    target_dir = _resolve_benchmark_results_dir(results_dir)

    payload = build_benchmark_dashboard(
        results_dir=target_dir,
        history_limit=history_limit,
        history_offset=history_offset,
        timeline_limit=timeline_limit,
        timeline_offset=timeline_offset,
        gate_min_candidate_score=gate_min_candidate_score,
        gate_max_negative_delta=gate_max_negative_delta,
        gate_require_non_regression=gate_require_non_regression,
        gate_require_improvement=gate_require_improvement,
    )
    return BenchmarkDashboardResponse(**payload)


@app.get("/v1/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    request: Request = None,
) -> JobListResponse:
    if status and status not in _LISTABLE_JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status filter must be one of: queued, running, completed, failed, canceled",
        )
    tenant_id = _tenant_id_for_request(request)
    items = _get_job_store().list_jobs(
        limit=limit,
        offset=offset,
        status=status,
        tenant_id=tenant_id,
    )
    return JobListResponse(
        items=items,
        total_returned=len(items),
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )


def _run_job(
    job_id: str,
    pdf_paths: list[str],
    analysis_mode: str,
    selected_trades: list[str],
    sheet_overrides: list[dict[str, object]] | None,
    spec_profiles: list[dict[str, object]] | None,
    notes: str | None,
    upload_dir: str | None,
    tenant_id: str = _DEFAULT_TENANT_ID,
) -> None:
    run_semaphore = _get_job_run_semaphore()
    run_semaphore.acquire()
    try:
        store = _get_job_store()
        started_at = _utc_now()
        claimed = store.transition_job_if_current(
            job_id,
            current_status="queued",
            status="running",
            updated_at=started_at,
            started_at=started_at,
            tenant_id=tenant_id,
        )
        if not claimed:
            return
        try:
            result = run_pipeline(
                pdf_paths=pdf_paths,
                analysis_mode=analysis_mode,
                selected_trades=selected_trades,
                sheet_overrides=sheet_overrides,
                spec_profiles=spec_profiles,
                notes=notes,
                validate_schema=True,
            )
            now = _utc_now()
            store.transition_job_if_current(
                job_id,
                current_status="running",
                status="completed",
                updated_at=now,
                completed_at=now,
                result=result,
                error=None,
                tenant_id=tenant_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            now = _utc_now()
            store.transition_job_if_current(
                job_id,
                current_status="running",
                status="failed",
                updated_at=now,
                completed_at=now,
                result=None,
                error=str(exc),
                tenant_id=tenant_id,
            )
    finally:
        run_semaphore.release()
        if upload_dir and _should_cleanup_uploads(mode="async"):
            shutil.rmtree(upload_dir, ignore_errors=True)


async def _save_uploads(
    files: list[UploadFile],
    target_dir: Path,
    *,
    allowed_suffixes: set[str] | None = None,
) -> list[str]:
    max_files = _resolve_max_upload_files()
    max_file_bytes = _resolve_max_upload_file_bytes()
    max_total_bytes = _resolve_max_upload_total_bytes()
    if len(files) > max_files:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload rejected: {len(files)} files exceeds limit of {max_files}. "
                "Reduce the number of files or increase AI_ESTIMATOR_MAX_UPLOAD_FILES."
            ),
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_paths: list[str] = []
    total_written = 0
    for index, upload in enumerate(files):
        suffix = Path(upload.filename or "drawing.pdf").suffix or ".pdf"
        suffix = suffix.lower()
        display_name = upload.filename or f"upload_{index + 1}{suffix}"
        if allowed_suffixes is not None:
            normalized_allowed = {item.lower() for item in allowed_suffixes}
            if suffix not in normalized_allowed:
                allowed_text = ", ".join(sorted(normalized_allowed))
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Upload rejected: '{display_name}' has unsupported "
                        f"file type '{suffix}'. Allowed file types: {allowed_text}."
                    ),
                )
        clean_name = _safe_file_name(Path(upload.filename or f"drawing_{index + 1}.pdf").stem)
        target_path = target_dir / f"{index + 1:03d}_{clean_name}{suffix}"
        file_written = 0
        try:
            with target_path.open("wb") as handle:
                while True:
                    chunk = await upload.read(_UPLOAD_CHUNK_SIZE_BYTES)
                    if not chunk:
                        break
                    chunk_size = len(chunk)
                    file_written += chunk_size
                    total_written += chunk_size
                    if file_written > max_file_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"Upload rejected: '{upload.filename or target_path.name}' is too large "
                                f"({file_written // (1024 * 1024)} MB). Limit is "
                                f"{max_file_bytes // (1024 * 1024)} MB per file "
                                "(AI_ESTIMATOR_MAX_UPLOAD_FILE_MB)."
                            ),
                        )
                    if total_written > max_total_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                "Upload rejected: total upload size exceeded limit "
                                f"of {max_total_bytes // (1024 * 1024)} MB "
                                "(AI_ESTIMATOR_MAX_UPLOAD_TOTAL_MB)."
                            ),
                        )
                    handle.write(chunk)
            if file_written <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Upload rejected: '{upload.filename or target_path.name}' is empty.",
                )
            pdf_paths.append(str(target_path))
        except HTTPException:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Upload failed while saving '{upload.filename or target_path.name}': {exc}",
            ) from exc
    return pdf_paths


def _resolve_benchmark_results_dir(results_dir: str) -> Path:
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd().joinpath("benchmarks", "results").resolve()
    _ensure_benchmark_path_allowed(target_dir)
    return target_dir


def _resolve_benchmark_report_path(report_path: str, *, label: str) -> Path:
    target = Path(str(report_path).strip()).expanduser().resolve()
    _ensure_benchmark_path_allowed(target)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"{label} report not found: {target}")
    return target


def _ensure_benchmark_path_allowed(target: Path) -> None:
    if _parse_bool_env(os.environ.get("AI_ESTIMATOR_ALLOW_ARBITRARY_BENCHMARK_PATHS", "")):
        return
    roots = _allowed_benchmark_roots()
    if any(_path_is_relative_to(target, root) for root in roots):
        return
    allowed = ", ".join(str(root) for root in roots)
    raise HTTPException(
        status_code=400,
        detail=(
            f"Benchmark path is outside allowed results directories: {target}. "
            f"Allowed roots: {allowed}. Set AI_ESTIMATOR_ALLOW_ARBITRARY_BENCHMARK_PATHS=true "
            "for local development only."
        ),
    )


def _allowed_benchmark_roots() -> list[Path]:
    roots = [Path.cwd().joinpath("benchmarks", "results")]
    configured = os.environ.get("AI_ESTIMATOR_BENCHMARK_RESULTS_DIRS", "").strip()
    if configured:
        roots.extend(Path(item).expanduser() for item in configured.split(os.pathsep) if item.strip())
    return [root.resolve() for root in roots]


def _path_is_relative_to(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path() -> str:
    override = os.environ.get("AI_ESTIMATOR_DB_PATH", "").strip()
    if override:
        return override
    return str(Path.cwd() / ".ai_estimator" / "jobs.db")


def _resolve_upload_root() -> str:
    override = os.environ.get("AI_ESTIMATOR_UPLOAD_DIR", "").strip()
    if override:
        return override
    return str(Path.cwd() / ".ai_estimator" / "uploads")


def _resolve_spec_store_path() -> str:
    override = os.environ.get("AI_ESTIMATOR_SPEC_STORE_PATH", "").strip()
    if override:
        return override
    return str(Path.cwd() / ".ai_estimator" / "spec_store.json")


def _resolve_positive_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def _resolve_max_upload_files() -> int:
    return _resolve_positive_int_env(
        "AI_ESTIMATOR_MAX_UPLOAD_FILES",
        default=20,
        minimum=1,
        maximum=500,
    )


def _resolve_max_upload_file_bytes() -> int:
    mb = _resolve_positive_int_env(
        "AI_ESTIMATOR_MAX_UPLOAD_FILE_MB",
        default=200,
        minimum=1,
        maximum=10_000,
    )
    return mb * 1024 * 1024


def _resolve_max_upload_total_bytes() -> int:
    mb = _resolve_positive_int_env(
        "AI_ESTIMATOR_MAX_UPLOAD_TOTAL_MB",
        default=1_000,
        minimum=1,
        maximum=50_000,
    )
    return mb * 1024 * 1024


def _resolve_max_queued_jobs() -> int | None:
    raw = os.environ.get("AI_ESTIMATOR_MAX_QUEUED_JOBS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return min(value, 100000)


def _resolve_auto_prune_on_submit() -> bool:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_ON_SUBMIT", "")
    return _parse_bool_env(raw)


def _resolve_auto_prune_older_than_hours() -> int | None:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 1:
        return None
    return min(value, 24 * 365 * 20)


def _resolve_auto_prune_limit() -> int:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_LIMIT", "").strip()
    if not raw:
        return 200
    try:
        value = int(raw)
    except ValueError:
        return 200
    return max(1, min(value, 1000))


def _resolve_auto_prune_cleanup_uploads() -> bool:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_CLEANUP_UPLOADS", "")
    return _parse_bool_env(raw)


def _maybe_auto_prune_jobs(*, tenant_id: str | None = None) -> dict[str, Any] | None:
    if not _resolve_auto_prune_on_submit():
        return None
    try:
        prune_kwargs: dict[str, Any] = {
            "statuses": "completed,failed,canceled",
            "older_than_hours": _resolve_auto_prune_older_than_hours(),
            "limit": _resolve_auto_prune_limit(),
            "dry_run": False,
            "cleanup_uploads": _resolve_auto_prune_cleanup_uploads(),
        }
        if tenant_id is not None:
            prune_kwargs["tenant_id"] = tenant_id
        payload = prune_jobs(
            **prune_kwargs,
        )
        return payload.model_dump()
    except Exception:
        # Auto-prune should never block the primary job submission path.
        return None


def _enforce_queued_job_limit(*, tenant_id: str | None = None) -> None:
    max_queued = _resolve_max_queued_jobs()
    if max_queued is None:
        return
    queued = _get_job_store().count_jobs(status="queued", tenant_id=tenant_id)
    if queued >= max_queued:
        raise HTTPException(
            status_code=429,
            detail=(
                "Job queue is at capacity. "
                f"queued={queued}, max_queued={max_queued}. "
                "Retry later or increase AI_ESTIMATOR_MAX_QUEUED_JOBS."
            ),
        )


def _resolve_job_worker_limit() -> int:
    default_limit = 4
    raw = os.environ.get("AI_ESTIMATOR_JOB_WORKERS", "").strip()
    if not raw:
        return default_limit
    try:
        value = int(raw)
    except ValueError:
        return default_limit
    return max(1, min(32, value))


def _get_job_run_semaphore() -> BoundedSemaphore:
    global _job_run_semaphore, _job_run_semaphore_limit
    with _resource_lock:
        limit = _resolve_job_worker_limit()
        if _job_run_semaphore is None or _job_run_semaphore_limit != limit:
            _job_run_semaphore = BoundedSemaphore(limit)
            _job_run_semaphore_limit = limit
    return _job_run_semaphore


def _should_cleanup_uploads(mode: str) -> bool:
    if mode not in {"sync", "async"}:
        raise ValueError("mode must be 'sync' or 'async'.")

    specific_var = (
        "AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS"
        if mode == "sync"
        else "AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS"
    )
    specific_raw = os.environ.get(specific_var)
    if specific_raw is not None:
        return _parse_bool_env(specific_raw)

    global_raw = os.environ.get("AI_ESTIMATOR_CLEANUP_UPLOADS")
    if global_raw is not None:
        return _parse_bool_env(global_raw)

    # Default behavior: clean up sync uploads, retain async uploads for reruns/audit.
    return mode == "sync"


def _parse_bool_env(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_uploaded_pdf_paths(source_input: dict[str, Any]) -> tuple[list[str], list[str]]:
    uploaded_files = source_input.get("uploaded_files")
    if not isinstance(uploaded_files, list):
        return [], []

    paths: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for item in uploaded_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        if Path(path).exists():
            paths.append(path)
        else:
            missing.append(path)
    return paths, missing


def _cleanup_upload_dirs_for_job(record: JobRecord) -> tuple[list[str], list[str]]:
    job_input = record.input if isinstance(record.input, dict) else {}
    uploaded_files = job_input.get("uploaded_files")
    if not isinstance(uploaded_files, list):
        return [], []

    root = _get_upload_root().resolve()
    candidate_dirs: list[Path] = []
    seen: set[str] = set()
    for item in uploaded_files:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            continue
        try:
            parent = Path(raw_path).expanduser().resolve(strict=False).parent
        except OSError:
            continue
        key = str(parent).lower()
        if key in seen:
            continue
        seen.add(key)
        candidate_dirs.append(parent)

    removed: list[str] = []
    skipped: list[str] = []
    for candidate in candidate_dirs:
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root):
            skipped.append(str(resolved))
            continue
        if not resolved.exists():
            continue
        shutil.rmtree(resolved, ignore_errors=True)
        removed.append(str(resolved))
    return removed, skipped


def _queue_rerun_job(
    *,
    source_job_id: str,
    tenant_id: str,
    pdf_paths: list[str],
    analysis_mode: str,
    selected_trades: list[str],
    sheet_overrides: list[dict[str, Any]] | None,
    spec_profiles: list[dict[str, Any]] | None,
    notes: str | None,
    extra_input: dict[str, Any],
) -> str:
    rerun_job_id = str(uuid.uuid4())
    now = _utc_now()
    payload_input: dict[str, Any] = {
        "analysis_mode": analysis_mode,
        "selected_trades": selected_trades,
        "sheet_overrides": sheet_overrides or [],
        "spec_profile_ids": [str(item.get("spec_id", "")).strip() for item in (spec_profiles or [])],
        "notes": notes,
        "tenant_id": tenant_id,
        "uploaded_files": [
            {
                "file_name": Path(path).name,
                "path": str(path),
            }
            for path in pdf_paths
        ],
        "rerun_of_job_id": source_job_id,
    }
    payload_input.update(extra_input)

    record = JobRecord(
        job_id=rerun_job_id,
        tenant_id=tenant_id,
        status="queued",
        created_at=now,
        updated_at=now,
        input=payload_input,
    )
    _get_job_store().create_job(record)

    thread = Thread(
        target=_run_job,
        kwargs={
            "job_id": rerun_job_id,
            "pdf_paths": pdf_paths,
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trades,
            "sheet_overrides": sheet_overrides,
            "spec_profiles": spec_profiles,
            "notes": notes,
            "upload_dir": None,
            "tenant_id": tenant_id,
        },
        daemon=True,
    )
    thread.start()
    return rerun_job_id


def _append_note(*, source_notes: str | None, marker: str) -> str:
    base = source_notes.strip() if isinstance(source_notes, str) else ""
    marker_clean = marker.strip()
    if not base:
        return marker_clean
    if marker_clean.lower() in base.lower():
        return base
    return f"{base}\n{marker_clean}"


def _is_api_key_authorized(*, expected: str, provided: str) -> bool:
    return bool(expected.strip()) and expected.strip() == provided.strip()


def _resolve_default_tenant_id() -> str:
    raw = os.environ.get("AI_ESTIMATOR_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID)
    token = str(raw).strip() or _DEFAULT_TENANT_ID
    try:
        return _normalize_tenant_id(token)
    except ValueError:
        return _DEFAULT_TENANT_ID


def _normalize_tenant_id(raw: str) -> str:
    token = str(raw).strip()
    if not token:
        raise ValueError("Tenant ID cannot be empty.")
    if not _TENANT_ID_PATTERN.match(token):
        raise ValueError(
            "Invalid tenant ID. Use 1-80 characters: letters, numbers, '.', '-', or '_'."
        )
    return token


def _tenant_id_for_request(
    request: Request | None,
    *,
    explicit_tenant_id: str | None = None,
) -> str:
    tenant_candidate = str(explicit_tenant_id or "").strip()
    if not tenant_candidate and request is not None:
        tenant_candidate = str(request.headers.get("x-tenant-id", "")).strip()

    if not tenant_candidate:
        require_header = _parse_bool_env(os.environ.get("AI_ESTIMATOR_REQUIRE_TENANT_ID", ""))
        if request is not None and require_header and explicit_tenant_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Tenant ID is required. Provide header 'x-tenant-id' or configure "
                    "AI_ESTIMATOR_DEFAULT_TENANT_ID."
                ),
            )
        return _resolve_default_tenant_id()

    try:
        return _normalize_tenant_id(tenant_candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _build_handoff_recommendation(
    *,
    review_queue_summary: dict[str, Any],
    trade_recommendation: dict[str, Any],
    trade_coverage: dict[str, Any],
    ops_gate: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    flagged_sheets = int(review_queue_summary.get("flagged_sheets", 0))
    if flagged_sheets > 0:
        reasons.append(f"{flagged_sheets} sheet(s) remain flagged in review queue.")

    needs_review_count = 0
    coverage_summary = trade_coverage.get("summary", {})
    if isinstance(coverage_summary, dict):
        raw_needs_review = coverage_summary.get("needs_review_count", 0)
        if isinstance(raw_needs_review, int):
            needs_review_count = raw_needs_review
    if needs_review_count > 0:
        reasons.append(f"{needs_review_count} trade(s) need coverage review.")

    if not bool(ops_gate.get("passed", False)):
        failure_count = len(ops_gate.get("failures", [])) if isinstance(ops_gate.get("failures"), list) else "n/a"
        reasons.append(f"Operations gate failed ({failure_count} failure(s)).")

    if trade_recommendation.get("needs_user_review") is True:
        reasons.append("Trade recommendation indicates elevated uncertainty.")

    if reasons:
        status = "blocked"
    elif trade_recommendation.get("recommended_mode") == "all":
        status = "review_required"
        reasons.append("Recommended mode is 'all'; verify scope before handoff.")
    else:
        status = "ready"
        reasons.append("No blocking findings in queue, coverage, or ops gate.")

    return {
        "status": status,
        "reasons": reasons,
    }


def _resolve_rerun_inputs(
    *,
    source_input: dict[str, Any],
    tenant_id: str,
    analysis_mode: str | None,
    selected_trades: str | None,
    sheet_overrides_json: str | None,
    spec_profile_ids: str | None,
    spec_organization: str | None,
    include_public_specs: bool | None,
    notes: str | None,
) -> tuple[
    str,
    list[str],
    list[dict[str, Any]] | None,
    list[dict[str, Any]],
    str,
    bool,
    str | None,
]:
    if analysis_mode is None:
        resolved_mode = str(source_input.get("analysis_mode", "auto")).strip() or "auto"
    else:
        resolved_mode = analysis_mode.strip()

    if selected_trades is None:
        raw_trades = source_input.get("selected_trades", [])
        if not isinstance(raw_trades, list):
            raw_trades = []
        csv = ",".join(str(item).strip() for item in raw_trades if str(item).strip())
        resolved_trades = sanitize_selected_trades(csv)
    else:
        resolved_trades = sanitize_selected_trades(selected_trades)
    _validate_analysis_scope(analysis_mode=resolved_mode, selected_trades=resolved_trades)

    if sheet_overrides_json is None:
        resolved_overrides = _normalize_sheet_overrides_from_input(source_input.get("sheet_overrides"))
    else:
        resolved_overrides = parse_sheet_overrides_json(sheet_overrides_json)

    if spec_profile_ids is None:
        raw_spec_ids = source_input.get("spec_profile_ids", [])
        if isinstance(raw_spec_ids, list):
            resolved_spec_profile_ids_csv = ",".join(
                str(item).strip() for item in raw_spec_ids if str(item).strip()
            )
        else:
            resolved_spec_profile_ids_csv = ""
    else:
        resolved_spec_profile_ids_csv = spec_profile_ids

    if spec_organization is None:
        resolved_spec_organization = str(source_input.get("spec_organization", "")).strip()
    else:
        resolved_spec_organization = spec_organization.strip()

    if include_public_specs is None:
        resolved_include_public_specs = bool(source_input.get("include_public_specs", False))
    else:
        resolved_include_public_specs = bool(include_public_specs)

    resolved_spec_profiles = _resolve_spec_profiles_for_request(
        spec_profile_ids_csv=resolved_spec_profile_ids_csv,
        spec_organization=resolved_spec_organization,
        include_public_specs=resolved_include_public_specs,
        tenant_id=tenant_id,
    )

    if notes is None:
        source_notes = source_input.get("notes")
        resolved_notes = normalize_notes(source_notes if isinstance(source_notes, str) else None)
    else:
        resolved_notes = normalize_notes(notes)

    return (
        resolved_mode,
        resolved_trades,
        resolved_overrides,
        resolved_spec_profiles,
        resolved_spec_organization,
        resolved_include_public_specs,
        resolved_notes,
    )


def _validate_analysis_scope(*, analysis_mode: str, selected_trades: list[str]) -> None:
    if analysis_mode not in {"auto", "selected", "all"}:
        raise ValueError("analysis_mode must be auto, selected, or all")
    if analysis_mode == "selected" and not selected_trades:
        raise ValueError(
            "selected_trades must include at least one valid trade when analysis_mode is selected"
        )


def _format_trade_label(trade: str) -> str:
    token_map = {
        "hvac": "HVAC",
        "it": "IT",
    }
    words = []
    for token in trade.split("_"):
        lower = token.lower()
        words.append(token_map.get(lower, token.capitalize()))
    return " ".join(words)


def _parse_prune_statuses_csv(raw: str) -> list[str]:
    token_map: list[str] = []
    seen: set[str] = set()
    for token in str(raw).split(","):
        normalized = token.strip().lower()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        token_map.append(normalized)
    if not token_map:
        token_map = sorted(_TERMINAL_JOB_STATUSES)

    invalid = [token for token in token_map if token not in _LISTABLE_JOB_STATUSES]
    if invalid:
        allowed = ", ".join(sorted(_LISTABLE_JOB_STATUSES))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prune statuses: {', '.join(invalid)}. Allowed: {allowed}.",
        )

    active = [token for token in token_map if token in _ACTIVE_JOB_STATUSES]
    if active:
        raise HTTPException(
            status_code=400,
            detail=(
                "Prune supports terminal statuses only. "
                f"Remove active statuses: {', '.join(active)}."
            ),
        )
    return token_map


def _normalize_sheet_overrides_from_input(raw: object) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {
            "sheet_id": str(item.get("sheet_id", "")).strip(),
            "title": str(item.get("title", "")).strip(),
        }
        source_page_index = item.get("source_page_index")
        if isinstance(source_page_index, int) and source_page_index >= 1:
            row["source_page_index"] = source_page_index
        elif isinstance(source_page_index, str):
            token = source_page_index.strip()
            if token.isdigit():
                value = int(token)
                if value >= 1:
                    row["source_page_index"] = value
        normalized.append(row)
    return normalized


def _safe_file_name(name: str) -> str:
    allowed = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in name)
    normalized = allowed.strip("_")
    return normalized[:80] or "drawing"


def _normalize_spec_item(raw: dict[str, Any]) -> dict[str, Any]:
    tenant_id = str(raw.get("tenant_id", "")).strip()
    if not tenant_id:
        tenant_id = "public" if bool(raw.get("is_public", False)) else _DEFAULT_TENANT_ID
    return {
        "spec_id": str(raw.get("spec_id", "")).strip(),
        "tenant_id": tenant_id,
        "title": str(raw.get("title", "")).strip(),
        "organization": str(raw.get("organization", "")).strip(),
        "agency": str(raw.get("agency", "")).strip(),
        "standard_name": str(raw.get("standard_name", "")).strip(),
        "project_type": str(raw.get("project_type", "")).strip(),
        "tags": [str(item).strip() for item in raw.get("tags", []) if str(item).strip()]
        if isinstance(raw.get("tags"), list)
        else [],
        "is_public": bool(raw.get("is_public", False)),
        "source_file_name": str(raw.get("source_file_name", "")).strip(),
        "source_file_path": str(raw.get("source_file_path", "")).strip(),
        "notes": str(raw.get("notes", "")).strip(),
        "detected_standard_refs": [
            str(item).strip().upper()
            for item in raw.get("detected_standard_refs", [])
            if str(item).strip()
        ]
        if isinstance(raw.get("detected_standard_refs"), list)
        else [],
        "detected_trade_hints": [
            str(item).strip()
            for item in raw.get("detected_trade_hints", [])
            if str(item).strip()
        ]
        if isinstance(raw.get("detected_trade_hints"), list)
        else [],
        "text_excerpt": str(raw.get("text_excerpt", "")).strip(),
        "created_at": str(raw.get("created_at", "")).strip() or _utc_now(),
        "updated_at": str(raw.get("updated_at", "")).strip() or _utc_now(),
    }


def _resolve_spec_profiles_for_request(
    *,
    spec_profile_ids_csv: str | None,
    spec_organization: str | None,
    include_public_specs: bool,
    tenant_id: str,
) -> list[dict[str, Any]]:
    spec_store = _get_spec_store()
    spec_ids = parse_csv_tokens(spec_profile_ids_csv)
    selected = spec_store.get_by_ids(spec_ids, tenant_id=tenant_id)

    if include_public_specs:
        public_matches, _total = spec_store.list_specs(
            organization=(spec_organization or "").strip(),
            public_only=True,
            tenant_id=tenant_id,
            limit=1000,
            offset=0,
        )
        selected_map: dict[str, dict[str, Any]] = {
            str(item.get("spec_id", "")).strip(): item for item in selected
        }
        for item in public_matches:
            spec_id = str(item.get("spec_id", "")).strip()
            if spec_id and spec_id not in selected_map:
                selected_map[spec_id] = item
        selected = list(selected_map.values())

    return [_normalize_spec_item(item) for item in selected]


def _resolve_web_submittal_lookup_enabled() -> bool:
    return _parse_bool_env(os.environ.get("AI_ESTIMATOR_ENABLE_WEB_SUBMITTALS", ""))


def _search_public_product_docs(*, query: str, limit: int) -> list[dict[str, str]]:
    import requests

    search_url = "https://duckduckgo.com/html/"
    results: list[dict[str, str]] = []
    try:
        response = requests.get(
            search_url,
            params={"q": query},
            timeout=20,
            headers={"User-Agent": "AI-Estimator/0.1"},
        )
        response.raise_for_status()
    except Exception:
        return results

    html = response.text
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        href = str(match.group("href")).strip()
        title = re.sub(r"<[^>]+>", "", str(match.group("title"))).strip()
        if not href:
            continue
        results.append({"query": query, "title": title, "url": href})
        if len(results) >= max(1, min(limit, 20)):
            break
    return results


def _get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        with _resource_lock:
            if _job_store is None:
                _job_store = JobStore(_resolve_db_path())
    return _job_store


def _get_spec_store() -> SpecStore:
    global _spec_store
    if _spec_store is None:
        with _resource_lock:
            if _spec_store is None:
                _spec_store = SpecStore(_resolve_spec_store_path())
    return _spec_store


def _get_upload_root() -> Path:
    global _upload_root
    if _upload_root is None:
        with _resource_lock:
            if _upload_root is None:
                _upload_root = Path(_resolve_upload_root())
                _upload_root.mkdir(parents=True, exist_ok=True)
    return _upload_root


