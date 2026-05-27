from __future__ import annotations

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(job_id: str, *, status: str, started_at: str | None = None, completed_at: str | None = None) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        started_at=started_at,
        completed_at=completed_at,
        input={"analysis_mode": "auto", "selected_trades": []},
        result={
            "sheets_detected": [{"sheet_id": "A101"}, {"sheet_id": "UNMAPPED_1"}],
            "issues_or_ambiguities": [],
            "scale_analysis": {
                "by_sheet": [
                    {"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\""},
                    {"sheet_id": "UNMAPPED_1", "detected_scale": None},
                ]
            },
            "legend_and_symbols": {"unknown_symbols": [{"symbol": "X1"}, {"symbol": "X2"}]},
        }
        if status == "completed"
        else None,
    )


def test_jobs_metrics_endpoint_returns_snapshot(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(
        _record(
            "job-1",
            status="completed",
            started_at="2026-05-27T00:00:02+00:00",
            completed_at="2026-05-27T00:00:20+00:00",
        )
    )
    store.create_job(
        _record(
            "job-2",
            status="failed",
            started_at="2026-05-27T00:00:03+00:00",
            completed_at="2026-05-27T00:00:10+00:00",
        )
    )
    store.create_job(_record("job-3", status="queued"))

    monkeypatch.setattr(service_app, "_job_store", store)
    response = service_app.get_job_metrics(window=500)

    payload = response.model_dump()
    assert payload["jobs_considered"] == 3
    assert payload["status_counts"]["completed"] == 1
    assert payload["status_counts"]["failed"] == 1
    assert payload["status_counts"]["queued"] == 1
    assert payload["active_jobs"] == 1
    assert payload["terminal_jobs"] == 2
    assert payload["failure_rate"] == 0.5
    assert payload["window_applied"] == 500
    assert payload["throughput_last_24h"]["terminal_jobs"] == 2
    assert payload["quality"]["completed_jobs_with_result"] == 1
    assert payload["quality"]["unmapped_sheet_id_count"] == 1
    assert payload["quality"]["missing_scale_count"] == 1


def test_jobs_metrics_endpoint_clamps_window(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-1", status="queued"))
    monkeypatch.setattr(service_app, "_job_store", store)
    response = service_app.get_job_metrics(window=999999)

    payload = response.model_dump()
    assert payload["window_requested"] == 999999
    assert payload["window_applied"] == 5000


def test_jobs_metrics_gate_endpoint_returns_pass_fail(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(
        _record(
            "job-1",
            status="completed",
            started_at="2026-05-27T00:00:01+00:00",
            completed_at="2026-05-27T00:00:10+00:00",
        )
    )
    store.create_job(
        _record(
            "job-2",
            status="failed",
            started_at="2026-05-27T00:00:01+00:00",
            completed_at="2026-05-27T00:00:10+00:00",
        )
    )
    monkeypatch.setattr(service_app, "_job_store", store)

    fail_payload = service_app.get_job_metrics_gate(
        window=500,
        max_failure_rate=0.1,
        max_active_jobs=0,
        max_missing_scale_rate=0.1,
        max_unmapped_sheet_rate=0.1,
        min_jobs_per_hour_24h=0.2,
    ).model_dump()
    assert fail_payload["passed"] is False
    assert len(fail_payload["failures"]) >= 1

    pass_payload = service_app.get_job_metrics_gate(
        window=500,
        max_failure_rate=0.8,
        max_active_jobs=10,
        max_missing_scale_rate=1.0,
        max_unmapped_sheet_rate=1.0,
        min_jobs_per_hour_24h=0.0,
    ).model_dump()
    assert pass_payload["passed"] is True
    assert pass_payload["failures"] == []
