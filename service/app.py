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

from ai_estimator.pipeline import run_pipeline, sanitize_selected_trades
from service.job_store import JobRecord, JobStore
from service.request_parsing import normalize_notes, parse_sheet_overrides_json
from service.review_queue import build_review_queue, build_sheet_overrides_template


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobListResponse(BaseModel):
    items: list[JobRecord]
    total_returned: int
    limit: int
    offset: int


class ReviewQueueResponse(BaseModel):
    job_id: str
    low_confidence_threshold: float
    summary: dict[str, Any]
    items: list[dict[str, Any]]


class SheetOverridesTemplateResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    items: list[dict[str, Any]]


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
        if _should_cleanup_uploads():
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
    upload_dir: str,
) -> None:
    _get_job_store().update_job(job_id, status="running", updated_at=_utc_now())
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
        if _should_cleanup_uploads():
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


def _should_cleanup_uploads() -> bool:
    raw = os.environ.get("AI_ESTIMATOR_CLEANUP_UPLOADS", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
