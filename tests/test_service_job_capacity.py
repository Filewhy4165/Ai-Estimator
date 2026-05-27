from __future__ import annotations

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(job_id: str, status: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
    )


def test_get_job_capacity_without_queue_cap(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-running", "running"))
    store.create_job(_record("job-queued", "queued"))
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "3")
    monkeypatch.delenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", raising=False)

    payload = service_app.get_job_capacity().model_dump()
    assert payload["worker_limit"] == 3
    assert payload["running_jobs"] == 1
    assert payload["queued_jobs"] == 1
    assert payload["running_slots_available"] == 2
    assert payload["max_queued_jobs"] is None
    assert payload["queue_capacity_remaining"] is None


def test_get_job_capacity_with_queue_cap(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-queued-1", "queued"))
    store.create_job(_record("job-queued-2", "queued"))
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "4")
    monkeypatch.setenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", "5")

    payload = service_app.get_job_capacity().model_dump()
    assert payload["worker_limit"] == 4
    assert payload["running_jobs"] == 0
    assert payload["queued_jobs"] == 2
    assert payload["running_slots_available"] == 4
    assert payload["max_queued_jobs"] == 5
    assert payload["queue_capacity_remaining"] == 3
