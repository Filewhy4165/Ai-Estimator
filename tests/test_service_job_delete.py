from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(
    job_id: str,
    *,
    status: str,
    uploaded_files: list[dict[str, str]] | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        completed_at="2026-05-27T00:00:10+00:00" if status in {"completed", "failed", "canceled"} else None,
        input={
            "analysis_mode": "auto",
            "selected_trades": [],
            "uploaded_files": uploaded_files or [],
        },
    )


def test_delete_terminal_job_removes_record(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-1", status="completed"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.delete_job("job-1").model_dump()
    assert payload["deleted"] is True
    assert payload["previous_status"] == "completed"
    assert payload["removed_upload_dirs"] == []
    assert payload["skipped_upload_dirs"] == []
    assert store.get_job("job-1") is None


def test_delete_job_rejects_active_status(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-running", status="running"))
    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.delete_job("job-running")
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected deleting active job to raise HTTPException(409)")


def test_delete_job_with_cleanup_removes_safe_dir_only(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))

    upload_root = (tmp_path / "uploads").resolve()
    safe_dir = (upload_root / "jobs" / "job-cleanup").resolve()
    safe_dir.mkdir(parents=True, exist_ok=True)
    safe_pdf = safe_dir / "001.pdf"
    safe_pdf.write_text("pdf", encoding="utf-8")

    outside_dir = (tmp_path / "outside").resolve()
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_pdf = outside_dir / "001.pdf"
    outside_pdf.write_text("pdf", encoding="utf-8")

    store.create_job(
        _record(
            "job-cleanup",
            status="failed",
            uploaded_files=[
                {"file_name": "001.pdf", "path": str(safe_pdf)},
                {"file_name": "001.pdf", "path": str(outside_pdf)},
            ],
        )
    )
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setattr(service_app, "_upload_root", upload_root)

    payload = service_app.delete_job("job-cleanup", cleanup_uploads=True).model_dump()
    assert payload["deleted"] is True
    assert str(safe_dir) in payload["removed_upload_dirs"]
    assert str(outside_dir) in payload["skipped_upload_dirs"]
    assert safe_dir.exists() is False
    assert outside_dir.exists() is True
    assert store.get_job("job-cleanup") is None


def test_delete_job_not_found(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.delete_job("missing")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected missing job to raise HTTPException(404)")
