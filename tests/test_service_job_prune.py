from __future__ import annotations

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(
    job_id: str,
    *,
    status: str,
    updated_at: str = "2026-05-27T00:00:00+00:00",
    uploaded_files: list[dict[str, str]] | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at=updated_at,
        completed_at="2026-05-27T00:00:10+00:00" if status in {"completed", "failed", "canceled"} else None,
        input={
            "analysis_mode": "auto",
            "selected_trades": [],
            "uploaded_files": uploaded_files or [],
        },
    )


def test_prune_jobs_dry_run_keeps_records(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-completed", status="completed"))
    store.create_job(_record("job-failed", status="failed"))
    store.create_job(_record("job-canceled", status="canceled"))
    store.create_job(_record("job-running", status="running"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.prune_jobs().model_dump()
    assert payload["dry_run"] is True
    assert payload["total_eligible"] == 3
    assert payload["total_deleted"] == 0
    assert sorted(payload["eligible_job_ids"]) == ["job-canceled", "job-completed", "job-failed"]
    assert store.count_jobs() == 4


def test_prune_jobs_deletes_terminal_records(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-completed", status="completed"))
    store.create_job(_record("job-failed", status="failed"))
    store.create_job(_record("job-running", status="running"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.prune_jobs(dry_run=False, limit=10).model_dump()
    assert payload["dry_run"] is False
    assert payload["total_eligible"] == 2
    assert payload["total_deleted"] == 2
    assert sorted(payload["deleted_job_ids"]) == ["job-completed", "job-failed"]
    assert store.count_jobs() == 1
    remaining = store.list_jobs(limit=10, offset=0)
    assert remaining[0].status == "running"


def test_prune_jobs_applies_older_than_cutoff(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(
        _record(
            "job-old",
            status="completed",
            updated_at="2026-05-01T00:00:00+00:00",
        )
    )
    store.create_job(
        _record(
            "job-future",
            status="completed",
            updated_at="2099-01-01T00:00:00+00:00",
        )
    )
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.prune_jobs(older_than_hours=1, dry_run=True, limit=10).model_dump()
    assert payload["total_eligible"] == 1
    assert payload["eligible_job_ids"] == ["job-old"]


def test_prune_jobs_rejects_active_status_tokens(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.prune_jobs(statuses="completed,running")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected active prune statuses to raise HTTPException(400)")


def test_prune_jobs_cleanup_uploads_respects_root(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))

    upload_root = (tmp_path / "uploads").resolve()
    safe_dir = (upload_root / "jobs" / "job-prune-cleanup").resolve()
    safe_dir.mkdir(parents=True, exist_ok=True)
    safe_pdf = safe_dir / "001.pdf"
    safe_pdf.write_text("pdf", encoding="utf-8")

    outside_dir = (tmp_path / "outside").resolve()
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_pdf = outside_dir / "001.pdf"
    outside_pdf.write_text("pdf", encoding="utf-8")

    store.create_job(
        _record(
            "job-prune-cleanup",
            status="failed",
            uploaded_files=[
                {"file_name": "001.pdf", "path": str(safe_pdf)},
                {"file_name": "001.pdf", "path": str(outside_pdf)},
            ],
        )
    )
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setattr(service_app, "_upload_root", upload_root)

    payload = service_app.prune_jobs(
        statuses="failed",
        dry_run=False,
        cleanup_uploads=True,
        limit=10,
    ).model_dump()
    assert payload["total_deleted"] == 1
    assert str(safe_dir) in payload["removed_upload_dirs"]
    assert str(outside_dir) in payload["skipped_upload_dirs"]
    assert safe_dir.exists() is False
    assert outside_dir.exists() is True
