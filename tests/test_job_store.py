from __future__ import annotations

from pathlib import Path

from service.job_store import JobRecord, JobStore


def test_job_store_create_update_get_and_list(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    store = JobStore(str(db_path))

    record = JobRecord(
        job_id="job-1",
        status="queued",
        created_at="2026-05-24T00:00:00+00:00",
        updated_at="2026-05-24T00:00:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
    )
    store.create_job(record)

    stored = store.get_job("job-1")
    assert stored is not None
    assert stored.status == "queued"
    assert stored.result is None

    store.update_job(
        "job-1",
        status="completed",
        updated_at="2026-05-24T00:01:00+00:00",
        completed_at="2026-05-24T00:01:00+00:00",
        result={"ok": True},
        error=None,
    )
    updated = store.get_job("job-1")
    assert updated is not None
    assert updated.status == "completed"
    assert updated.result == {"ok": True}
    assert updated.completed_at == "2026-05-24T00:01:00+00:00"

    listed = store.list_jobs(limit=10, offset=0)
    assert len(listed) == 1
    assert listed[0].job_id == "job-1"

