from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
from service.job_metrics import build_job_metrics_snapshot
from service.job_store import JobRecord, JobStore
from service.request_parsing import normalize_notes, parse_sheet_overrides_json
from service.review_queue import (
    build_benchmark_manifest_template,
    build_review_queue,
    build_sheet_overrides_template,
)


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db_path": _get_job_store().db_path}


@app.post("/v1/analyze")
async def analyze(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
    sheet_overrides_json: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict[str, Any]:
    if analysis_mode not in {"auto", "selected", "all"}:
        raise HTTPException(status_code=400, detail="analysis_mode must be auto, selected, or all")

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
            selected_trades=sanitize_selected_trades(selected_trades),
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
    if analysis_mode not in {"auto", "selected", "all"}:
        raise HTTPException(status_code=400, detail="analysis_mode must be auto, selected, or all")

    job_id = str(uuid.uuid4())
    selected_trade_list = sanitize_selected_trades(selected_trades)
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

    rerun_job_id = str(uuid.uuid4())
    now = _utc_now()
    record = JobRecord(
        job_id=rerun_job_id,
        status="queued",
        created_at=now,
        updated_at=now,
        input={
            "analysis_mode": resolved_mode,
            "selected_trades": resolved_trades,
            "sheet_overrides": resolved_overrides or [],
            "notes": resolved_notes,
            "uploaded_files": [
                {
                    "file_name": Path(path).name,
                    "path": str(path),
                }
                for path in pdf_paths
            ],
            "rerun_of_job_id": job_id,
        },
    )
    _get_job_store().create_job(record)

    thread = Thread(
        target=_run_job,
        kwargs={
            "job_id": rerun_job_id,
            "pdf_paths": pdf_paths,
            "analysis_mode": resolved_mode,
            "selected_trades": resolved_trades,
            "sheet_overrides": resolved_overrides,
            "notes": resolved_notes,
            "upload_dir": None,
        },
        daemon=True,
    )
    thread.start()
    return JobCreateResponse(job_id=rerun_job_id, status="queued")


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
    if status and status not in {"queued", "running", "completed", "failed"}:
        raise HTTPException(
            status_code=400,
            detail="status filter must be one of: queued, running, completed, failed",
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
    started_at = _utc_now()
    _get_job_store().update_job(
        job_id,
        status="running",
        updated_at=started_at,
        started_at=started_at,
    )
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
        _get_job_store().update_job(
            job_id,
            status="completed",
            updated_at=now,
            completed_at=now,
            result=result,
            error=None,
        )
    except Exception as exc:  # pragma: no cover - defensive
        now = _utc_now()
        _get_job_store().update_job(
            job_id,
            status="failed",
            updated_at=now,
            completed_at=now,
            result=None,
            error=str(exc),
        )
    finally:
        if upload_dir and _should_cleanup_uploads(mode="async"):
            shutil.rmtree(upload_dir, ignore_errors=True)


async def _save_uploads(files: list[UploadFile], target_dir: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_paths: list[str] = []
    for index, upload in enumerate(files):
        suffix = Path(upload.filename or "drawing.pdf").suffix or ".pdf"
        clean_name = _safe_file_name(Path(upload.filename or f"drawing_{index + 1}.pdf").stem)
        target_path = target_dir / f"{index + 1:03d}_{clean_name}{suffix}"
        content = await upload.read()
        target_path.write_bytes(content)
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
    if resolved_mode not in {"auto", "selected", "all"}:
        raise ValueError("analysis_mode must be auto, selected, or all")

    if selected_trades is None:
        raw_trades = source_input.get("selected_trades", [])
        if not isinstance(raw_trades, list):
            raw_trades = []
        csv = ",".join(str(item).strip() for item in raw_trades if str(item).strip())
        resolved_trades = sanitize_selected_trades(csv)
    else:
        resolved_trades = sanitize_selected_trades(selected_trades)

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
