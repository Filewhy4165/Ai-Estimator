from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_estimator.pipeline import run_pipeline, sanitize_selected_trades


class JobRecord(BaseModel):
    job_id: str
    status: str
    created_at: str
    completed_at: str | None = None
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


app = FastAPI(title="AI Estimator Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, JobRecord] = {}
_job_lock = Lock()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/analyze")
async def analyze(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
) -> dict[str, Any]:
    if analysis_mode not in {"auto", "selected", "all"}:
        raise HTTPException(status_code=400, detail="analysis_mode must be auto, selected, or all")

    pdf_paths = await _save_uploads(files)
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    payload = run_pipeline(
        pdf_paths=pdf_paths,
        analysis_mode=analysis_mode,
        selected_trades=sanitize_selected_trades(selected_trades),
        validate_schema=True,
    )
    return payload


@app.post("/v1/jobs")
async def create_job(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
) -> dict[str, Any]:
    if analysis_mode not in {"auto", "selected", "all"}:
        raise HTTPException(status_code=400, detail="analysis_mode must be auto, selected, or all")

    pdf_paths = await _save_uploads(files)
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    job_id = str(uuid.uuid4())
    record = JobRecord(
        job_id=job_id,
        status="queued",
        created_at=_utc_now(),
        input={
            "analysis_mode": analysis_mode,
            "selected_trades": sanitize_selected_trades(selected_trades),
            "files": [Path(path).name for path in pdf_paths],
        },
    )
    with _job_lock:
        _jobs[job_id] = record

    thread = Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "pdf_paths": pdf_paths,
            "analysis_mode": analysis_mode,
            "selected_trades": sanitize_selected_trades(selected_trades),
        },
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with _job_lock:
        record = _jobs.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(record.model_dump_json())


def _run_job(job_id: str, pdf_paths: list[str], analysis_mode: str, selected_trades: list[str]) -> None:
    with _job_lock:
        record = _jobs[job_id]
        record.status = "running"
        _jobs[job_id] = record

    try:
        result = run_pipeline(
            pdf_paths=pdf_paths,
            analysis_mode=analysis_mode,
            selected_trades=selected_trades,
            validate_schema=True,
        )
        with _job_lock:
            record = _jobs[job_id]
            record.status = "completed"
            record.completed_at = _utc_now()
            record.result = result
            _jobs[job_id] = record
    except Exception as exc:  # pragma: no cover - defensive
        with _job_lock:
            record = _jobs[job_id]
            record.status = "failed"
            record.error = str(exc)
            record.completed_at = _utc_now()
            _jobs[job_id] = record


async def _save_uploads(files: list[UploadFile]) -> list[str]:
    pdf_paths: list[str] = []
    for upload in files:
        suffix = Path(upload.filename or "drawing.pdf").suffix or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await upload.read()
            tmp.write(content)
            pdf_paths.append(tmp.name)
    return pdf_paths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

