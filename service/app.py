from __future__ import annotations

import os
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
from service.job_metrics import build_job_metrics_snapshot, evaluate_job_metrics_gate
from service.job_store import JobRecord, JobStore
from service.request_parsing import normalize_notes, parse_sheet_overrides_json
from service.review_queue import (
    build_benchmark_manifest_template,
    build_review_queue,
    build_sheet_overrides_template,
)
from service.trade_coverage import build_trade_coverage_report
from service.trade_recommendation import build_trade_recommendation


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_job_store: JobStore | None = None
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


@app.post("/v1/analyze")
async def analyze(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
    sheet_overrides_json: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict[str, Any]:
    selected_trade_list = sanitize_selected_trades(selected_trades)
    try:
        _validate_analysis_scope(analysis_mode=analysis_mode, selected_trades=selected_trade_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request_id = str(uuid.uuid4())
    request_dir = _get_upload_root() / "sync" / request_id
    pdf_paths = await _save_uploads(files, request_dir)
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        sheet_overrides = parse_sheet_overrides_json(sheet_overrides_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_notes = normalize_notes(notes)

    try:
        payload = run_pipeline(
            pdf_paths=pdf_paths,
            analysis_mode=analysis_mode,
            selected_trades=selected_trade_list,
            sheet_overrides=sheet_overrides,
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
    notes: str | None = Form(None),
) -> JobCreateResponse:
    selected_trade_list = sanitize_selected_trades(selected_trades)
    try:
        _validate_analysis_scope(analysis_mode=analysis_mode, selected_trades=selected_trade_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _maybe_auto_prune_jobs()
    _enforce_queued_job_limit()

    job_id = str(uuid.uuid4())
    job_upload_dir = _get_upload_root() / "jobs" / job_id
    pdf_paths = await _save_uploads(files, job_upload_dir)
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        sheet_overrides = parse_sheet_overrides_json(sheet_overrides_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_notes = normalize_notes(notes)

    now = _utc_now()
    record = JobRecord(
        job_id=job_id,
        status="queued",
        created_at=now,
        updated_at=now,
        input={
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trade_list,
            "sheet_overrides": sheet_overrides or [],
            "notes": normalized_notes,
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
            "notes": normalized_notes,
            "upload_dir": str(job_upload_dir),
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
    notes: str | None = Form(None),
) -> JobCreateResponse:
    _maybe_auto_prune_jobs()
    _enforce_queued_job_limit()
    source_record = _get_job_store().get_job(job_id)
    if not source_record:
        raise HTTPException(status_code=404, detail="Job not found")

    source_input = source_record.input if isinstance(source_record.input, dict) else {}
    try:
        (
            resolved_mode,
            resolved_trades,
            resolved_overrides,
            resolved_notes,
        ) = _resolve_rerun_inputs(
            source_input=source_input,
            analysis_mode=analysis_mode,
            selected_trades=selected_trades,
            sheet_overrides_json=sheet_overrides_json,
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
        pdf_paths=pdf_paths,
        analysis_mode=resolved_mode,
        selected_trades=resolved_trades,
        sheet_overrides=resolved_overrides,
        notes=resolved_notes,
        extra_input={},
    )
    return JobCreateResponse(job_id=rerun_job_id, status="queued")


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobCancelResponse)
def cancel_job(job_id: str) -> JobCancelResponse:
    store = _get_job_store()
    record = store.get_job(job_id)
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

    latest = store.get_job(job_id)
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
def delete_job(job_id: str, cleanup_uploads: bool = False) -> JobDeleteResponse:
    store = _get_job_store()
    record = store.get_job(job_id)
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

    deleted = store.delete_job(job_id)
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
) -> JobPruneResponse:
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
        latest = store.get_job(candidate.job_id)
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

        deleted = store.delete_job(latest.job_id)
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
def rerun_job_with_recommendation(job_id: str) -> JobRerunRecommendationResponse:
    _maybe_auto_prune_jobs()
    _enforce_queued_job_limit()
    source_record = _get_job_store().get_job(job_id)
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

    rerun_job_id = _queue_rerun_job(
        source_job_id=job_id,
        pdf_paths=pdf_paths,
        analysis_mode=recommended_mode,
        selected_trades=recommended_trades,
        sheet_overrides=resolved_overrides,
        notes=resolved_notes,
        extra_input={
            "trade_recommendation": {
                "recommended_mode": recommended_mode,
                "recommended_trades": recommended_trades,
                "confidence": recommendation.get("confidence"),
            }
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
def get_job_metrics(window: int = 200) -> JobMetricsResponse:
    window_applied = max(1, min(window, 5000))
    records = _get_job_store().list_recent_jobs(limit=window_applied)
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
) -> JobMetricsGateResponse:
    window_applied = max(1, min(window, 5000))
    records = _get_job_store().list_recent_jobs(limit=window_applied)
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
def get_job_capacity() -> JobCapacityResponse:
    store = _get_job_store()
    worker_limit = _resolve_job_worker_limit()
    running_jobs = store.count_jobs(status="running")
    queued_jobs = store.count_jobs(status="queued")
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
def get_job(job_id: str) -> dict[str, Any]:
    record = _get_job_store().get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return record.model_dump()


@app.get("/v1/jobs/{job_id}/review-queue", response_model=ReviewQueueResponse)
def get_job_review_queue(
    job_id: str,
    low_confidence_threshold: float = 0.75,
    include_only_flagged: bool = True,
) -> ReviewQueueResponse:
    if low_confidence_threshold < 0 or low_confidence_threshold > 1:
        raise HTTPException(status_code=400, detail="low_confidence_threshold must be between 0 and 1.")
    record = _get_job_store().get_job(job_id)
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
) -> SheetOverridesTemplateResponse:
    record = _get_job_store().get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_sheet_overrides_template(
        job_id=job_id,
        result=record.result,
        include_all=include_all,
    )
    return SheetOverridesTemplateResponse(**payload)


@app.get("/v1/jobs/{job_id}/trade-recommendation", response_model=TradeRecommendationResponse)
def get_trade_recommendation(job_id: str) -> TradeRecommendationResponse:
    record = _get_job_store().get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_trade_recommendation(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return TradeRecommendationResponse(**payload)


@app.get("/v1/jobs/{job_id}/trade-coverage", response_model=TradeCoverageResponse)
def get_trade_coverage(job_id: str) -> TradeCoverageResponse:
    record = _get_job_store().get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_trade_coverage_report(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return TradeCoverageResponse(**payload)


@app.get("/v1/jobs/{job_id}/readiness-report", response_model=JobReadinessReportResponse)
def get_job_readiness_report(job_id: str) -> JobReadinessReportResponse:
    record = _get_job_store().get_job(job_id)
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

    recent_records = _get_job_store().list_recent_jobs(limit=500)
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
) -> BenchmarkTemplateResponse:
    record = _get_job_store().get_job(job_id)
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
    baseline = Path(str(baseline_path).strip()).expanduser().resolve()
    candidate = Path(str(candidate_path).strip()).expanduser().resolve()
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
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd() / "benchmarks" / "results"

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
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd() / "benchmarks" / "results"

    payload = build_benchmark_history(results_dir=target_dir, limit=limit, offset=offset)
    return BenchmarkHistoryResponse(**payload)


@app.get("/v1/benchmark-reports/trend", response_model=BenchmarkTrendResponse)
def get_benchmark_reports_trend(
    results_dir: str = "",
) -> BenchmarkTrendResponse:
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd() / "benchmarks" / "results"

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
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd() / "benchmarks" / "results"

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
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd() / "benchmarks" / "results"

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
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd() / "benchmarks" / "results"

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
) -> JobListResponse:
    if status and status not in _LISTABLE_JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status filter must be one of: queued, running, completed, failed, canceled",
        )
    items = _get_job_store().list_jobs(limit=limit, offset=offset, status=status)
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
    notes: str | None,
    upload_dir: str | None,
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
        )
        if not claimed:
            return
        try:
            result = run_pipeline(
                pdf_paths=pdf_paths,
                analysis_mode=analysis_mode,
                selected_trades=selected_trades,
                sheet_overrides=sheet_overrides,
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
            )
    finally:
        run_semaphore.release()
        if upload_dir and _should_cleanup_uploads(mode="async"):
            shutil.rmtree(upload_dir, ignore_errors=True)


async def _save_uploads(files: list[UploadFile], target_dir: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_paths: list[str] = []
    for index, upload in enumerate(files):
        suffix = Path(upload.filename or "drawing.pdf").suffix or ".pdf"
        clean_name = _safe_file_name(Path(upload.filename or f"drawing_{index + 1}.pdf").stem)
        target_path = target_dir / f"{index + 1:03d}_{clean_name}{suffix}"
        with target_path.open("wb") as handle:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
        pdf_paths.append(str(target_path))
    return pdf_paths


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


def _maybe_auto_prune_jobs() -> dict[str, Any] | None:
    if not _resolve_auto_prune_on_submit():
        return None
    try:
        payload = prune_jobs(
            statuses="completed,failed,canceled",
            older_than_hours=_resolve_auto_prune_older_than_hours(),
            limit=_resolve_auto_prune_limit(),
            dry_run=False,
            cleanup_uploads=_resolve_auto_prune_cleanup_uploads(),
        )
        return payload.model_dump()
    except Exception:
        # Auto-prune should never block the primary job submission path.
        return None


def _enforce_queued_job_limit() -> None:
    max_queued = _resolve_max_queued_jobs()
    if max_queued is None:
        return
    queued = _get_job_store().count_jobs(status="queued")
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
    pdf_paths: list[str],
    analysis_mode: str,
    selected_trades: list[str],
    sheet_overrides: list[dict[str, Any]] | None,
    notes: str | None,
    extra_input: dict[str, Any],
) -> str:
    rerun_job_id = str(uuid.uuid4())
    now = _utc_now()
    payload_input: dict[str, Any] = {
        "analysis_mode": analysis_mode,
        "selected_trades": selected_trades,
        "sheet_overrides": sheet_overrides or [],
        "notes": notes,
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
            "notes": notes,
            "upload_dir": None,
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
    analysis_mode: str | None,
    selected_trades: str | None,
    sheet_overrides_json: str | None,
    notes: str | None,
) -> tuple[str, list[str], list[dict[str, Any]] | None, str | None]:
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

    if notes is None:
        source_notes = source_input.get("notes")
        resolved_notes = normalize_notes(source_notes if isinstance(source_notes, str) else None)
    else:
        resolved_notes = normalize_notes(notes)

    return resolved_mode, resolved_trades, resolved_overrides, resolved_notes


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


def _get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        with _resource_lock:
            if _job_store is None:
                _job_store = JobStore(_resolve_db_path())
    return _job_store


def _get_upload_root() -> Path:
    global _upload_root
    if _upload_root is None:
        with _resource_lock:
            if _upload_root is None:
                _upload_root = Path(_resolve_upload_root())
                _upload_root.mkdir(parents=True, exist_ok=True)
    return _upload_root
