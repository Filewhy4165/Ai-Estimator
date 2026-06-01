from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _request_for_tenant(tenant_id: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/jobs/job-a/visual-evidence",
            "query_string": b"",
            "headers": [(b"x-tenant-id", tenant_id.encode("utf-8"))],
        }
    )


def test_visual_evidence_endpoint_is_tenant_scoped(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(
        JobRecord(
            job_id="job-a",
            tenant_id="tenant-a",
            status="completed",
            created_at="2026-05-31T00:00:00+00:00",
            updated_at="2026-05-31T00:00:00+00:00",
            input={"analysis_mode": "auto", "selected_trades": []},
            result={
                "geometry": {
                    "annotations": {
                        "vector_pages": [{"sheet_id": "A101"}],
                        "vector_evidence": [{"sheet_id": "A101", "kind": "line"}],
                        "vector_measurements": [
                            {
                                "sheet_id": "A101",
                                "line_count": 1,
                                "rectangle_count": 0,
                                "total_linework_pdf_units": 100.0,
                            }
                        ],
                    }
                }
            },
        )
    )
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.get_job_visual_evidence(
        "job-a",
        request=_request_for_tenant("tenant-a"),
    )

    assert payload["summary"]["vector_page_count"] == 1
    assert payload["items"] == [{"sheet_id": "A101", "kind": "line"}]

    try:
        service_app.get_job_visual_evidence("job-a", request=_request_for_tenant("tenant-b"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected cross-tenant visual evidence lookup to fail")
