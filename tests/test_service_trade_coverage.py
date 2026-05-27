from __future__ import annotations

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(job_id: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status="completed",
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:10+00:00",
        completed_at="2026-05-27T00:00:10+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
        result={
            "trade_scope": {
                "detected_trades": ["architectural", "electrical"],
                "analyzed_trades": ["architectural"],
            },
            "geometry": {
                "walls": [{"trade": "architectural"}],
                "doors": [],
                "windows": [],
                "slabs": [],
                "roofs": [],
                "fixtures": [],
                "equipment": [],
                "annotations": {},
            },
            "quantity_takeoff": {
                "by_trade": {
                    "architectural": {"counts": {"door": 1}, "linear": {}, "area": {}, "volume": {}}
                }
            },
        },
    )


def test_get_trade_coverage_endpoint(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-1"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.get_trade_coverage("job-1").model_dump()
    assert payload["job_id"] == "job-1"
    assert payload["summary"]["total_trades"] == 2
    assert payload["summary"]["status_counts"]["covered"] == 1
    assert payload["summary"]["status_counts"]["skipped"] == 1


def test_get_trade_coverage_404(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.get_trade_coverage("missing")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected missing job to raise 404")
