from __future__ import annotations

from fastapi import HTTPException

import service.app as service_app
from service.job_store import JobRecord, JobStore


class _DummyThread:
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def start(self) -> None:
        return None


def test_rerun_recommended_queues_job_with_recommended_scope(monkeypatch, tmp_path):
    pdf_path = tmp_path / "drawing.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    store = JobStore(str(tmp_path / "jobs.db"))
    source = JobRecord(
        job_id="source-job",
        status="completed",
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:10+00:00",
        completed_at="2026-05-27T00:00:10+00:00",
        input={
            "analysis_mode": "auto",
            "selected_trades": [],
            "sheet_overrides": [{"sheet_id": "A101", "title": "Floor Plan"}],
            "notes": "Baseline rerun note.",
            "uploaded_files": [{"file_name": "drawing.pdf", "path": str(pdf_path)}],
        },
        result={
            "trade_scope": {
                "requested_mode": "auto",
                "requested_trades": [],
                "detected_trades": ["architectural", "electrical"],
                "sheet_trade_map": [
                    {"sheet": "A101", "trade": "architectural", "confidence": 0.9},
                    {"sheet": "E101", "trade": "electrical", "confidence": 0.75},
                ],
            }
        },
    )
    store.create_job(source)

    monkeypatch.setattr(service_app, "_job_store", store)
    monkeypatch.setattr(service_app, "Thread", _DummyThread)

    response = service_app.rerun_job_with_recommendation("source-job")
    payload = response.model_dump()

    assert payload["status"] == "queued"
    assert payload["source_job_id"] == "source-job"
    assert payload["recommended_mode"] == "selected"
    assert payload["recommended_trades"] == ["architectural", "electrical"]

    created = store.get_job(payload["job_id"])
    assert created is not None
    assert created.input["analysis_mode"] == "selected"
    assert created.input["selected_trades"] == ["architectural", "electrical"]
    assert created.input["rerun_of_job_id"] == "source-job"
    assert isinstance(created.input.get("trade_recommendation"), dict)


def test_rerun_recommended_returns_409_when_source_uploads_missing(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    source = JobRecord(
        job_id="source-missing",
        status="completed",
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:10+00:00",
        completed_at="2026-05-27T00:00:10+00:00",
        input={
            "analysis_mode": "auto",
            "selected_trades": [],
            "uploaded_files": [{"file_name": "drawing.pdf", "path": str(tmp_path / "missing.pdf")}],
        },
        result={},
    )
    store.create_job(source)

    monkeypatch.setattr(service_app, "_job_store", store)

    try:
        service_app.rerun_job_with_recommendation("source-missing")
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected 409 when uploaded files are missing")
