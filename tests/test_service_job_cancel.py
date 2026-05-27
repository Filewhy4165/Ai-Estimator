from __future__ import annotations

from threading import BoundedSemaphore

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(job_id: str, *, status: str, started_at: str | None = None) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        started_at=started_at,
        input={"analysis_mode": "auto", "selected_trades": []},
    )


def test_cancel_job_queued_transitions_to_canceled(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-queued", status="queued"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.cancel_job("job-queued").model_dump()
    assert payload["job_id"] == "job-queued"
    assert payload["status"] == "canceled"
    assert payload["previous_status"] == "queued"

    updated = store.get_job("job-queued")
    assert updated is not None
    assert updated.status == "canceled"
    assert updated.completed_at is not None
    assert "canceled" in str(updated.error).lower()


def test_cancel_job_running_transitions_to_canceled(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(
        _record(
            "job-running",
            status="running",
            started_at="2026-05-27T00:00:05+00:00",
        )
    )
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.cancel_job("job-running").model_dump()
    assert payload["status"] == "canceled"
    assert payload["previous_status"] == "running"

    updated = store.get_job("job-running")
    assert updated is not None
    assert updated.status == "canceled"
    assert updated.started_at == "2026-05-27T00:00:05+00:00"


def test_cancel_job_is_idempotent_for_already_canceled(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-canceled", status="canceled"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.cancel_job("job-canceled").model_dump()
    assert payload["status"] == "canceled"
    assert payload["previous_status"] == "canceled"


def test_cancel_job_rejects_completed(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-done", status="completed"))
    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.cancel_job("job-done")
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected completed job cancellation to raise HTTPException(409)")


def test_list_jobs_accepts_canceled_status_filter(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-canceled", status="canceled"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.list_jobs(status="canceled").model_dump()
    assert payload["total_returned"] == 1
    assert payload["items"][0]["status"] == "canceled"


def test_run_job_skips_pipeline_when_job_no_longer_queued(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-canceled", status="canceled"))
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setattr(service_app, "_get_job_run_semaphore", lambda: BoundedSemaphore(1))

    called = {"value": False}

    def _fake_run_pipeline(**kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return {"ok": True}

    monkeypatch.setattr(service_app, "run_pipeline", _fake_run_pipeline)

    service_app._run_job(
        job_id="job-canceled",
        pdf_paths=["C:\\tmp\\drawing.pdf"],
        analysis_mode="auto",
        selected_trades=[],
        sheet_overrides=None,
        notes=None,
        upload_dir=None,
    )

    assert called["value"] is False
    updated = store.get_job("job-canceled")
    assert updated is not None
    assert updated.status == "canceled"


def test_run_job_does_not_overwrite_canceled_state(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-queued", status="queued"))
    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setattr(service_app, "_get_job_run_semaphore", lambda: BoundedSemaphore(1))

    def _fake_run_pipeline(**kwargs):  # type: ignore[no-untyped-def]
        store.transition_job_if_current(
            "job-queued",
            current_status="running",
            status="canceled",
            updated_at="2026-05-27T00:00:10+00:00",
            completed_at="2026-05-27T00:00:10+00:00",
            error="Job canceled in-flight.",
        )
        return {"ok": True}

    monkeypatch.setattr(service_app, "run_pipeline", _fake_run_pipeline)

    service_app._run_job(
        job_id="job-queued",
        pdf_paths=["C:\\tmp\\drawing.pdf"],
        analysis_mode="auto",
        selected_trades=[],
        sheet_overrides=None,
        notes=None,
        upload_dir=None,
    )

    updated = store.get_job("job-queued")
    assert updated is not None
    assert updated.status == "canceled"
    assert updated.result is None
