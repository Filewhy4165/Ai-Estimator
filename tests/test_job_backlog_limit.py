from __future__ import annotations

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _queued_record(job_id: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status="queued",
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
    )


def test_resolve_max_queued_jobs(monkeypatch):
    monkeypatch.delenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", raising=False)
    assert service_app._resolve_max_queued_jobs() is None

    monkeypatch.setenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", "invalid")
    assert service_app._resolve_max_queued_jobs() is None

    monkeypatch.setenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", "0")
    assert service_app._resolve_max_queued_jobs() is None

    monkeypatch.setenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", "25")
    assert service_app._resolve_max_queued_jobs() == 25


def test_enforce_queued_job_limit_raises_429(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_queued_record("job-1"))
    store.create_job(_queued_record("job-2"))
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", "2")

    try:
        service_app._enforce_queued_job_limit()
    except HTTPException as exc:
        assert exc.status_code == 429
        assert "queued=2" in str(exc.detail)
    else:
        raise AssertionError("Expected queue limit to raise HTTPException(429)")


def test_enforce_queued_job_limit_allows_when_under_limit(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_queued_record("job-1"))
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setenv("AI_ESTIMATOR_MAX_QUEUED_JOBS", "2")

    service_app._enforce_queued_job_limit()
