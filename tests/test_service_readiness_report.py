from __future__ import annotations

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(job_id: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status="completed",
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:05:00+00:00",
        started_at="2026-05-27T00:00:10+00:00",
        completed_at="2026-05-27T00:05:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
        result={
            "sheets_detected": [
                {
                    "sheet_id": "UNMAPPED_doc_1",
                    "title": "Untitled",
                    "confidence": 0.42,
                    "source_page_index": 1,
                    "discipline": "electrical",
                }
            ],
            "trade_scope": {
                "requested_mode": "auto",
                "requested_trades": [],
                "detected_trades": ["electrical"],
                "analyzed_trades": ["electrical"],
                "sheet_trade_map": [{"sheet": "UNMAPPED_doc_1", "trade": "electrical", "confidence": 0.42}],
            },
            "scale_analysis": {"by_sheet": [{"sheet_id": "UNMAPPED_doc_1", "detected_scale": None}]},
            "legend_and_symbols": {"unknown_symbols": [{"sheet_id": "UNMAPPED_doc_1", "symbol": "X1"}]},
            "geometry": {
                "walls": [],
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
                    "electrical": {"counts": {}, "linear": {}, "area": {}, "volume": {}}
                }
            },
            "issues_or_ambiguities": [],
        },
    )


def test_get_job_readiness_report(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-1"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.get_job_readiness_report("job-1").model_dump()
    assert payload["job_id"] == "job-1"
    assert isinstance(payload["review_queue_summary"], dict)
    assert isinstance(payload["trade_recommendation"], dict)
    assert isinstance(payload["trade_coverage"], dict)
    assert isinstance(payload["ops_gate"], dict)
    assert payload["handoff_recommendation"]["status"] == "blocked"
    assert len(payload["handoff_recommendation"]["reasons"]) >= 1


def test_get_job_readiness_report_404(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.get_job_readiness_report("missing")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected missing job to raise 404")
