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
                        "vector_evidence": [
                            {
                                "sheet_id": "A101",
                                "source_page_index": 1,
                                "kind": "line",
                                "points": [[0, 0], [100, 0]],
                            }
                        ],
                        "vector_measurements": [
                            {
                                "sheet_id": "A101",
                                "source_page_index": 1,
                                "line_count": 1,
                                "rectangle_count": 0,
                                "line_length_pdf_units": 100.0,
                                "rectangle_perimeter_pdf_units": 0.0,
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
    assert payload["items"] == [
        {
            "sheet_id": "A101",
            "source_page_index": 1,
            "kind": "line",
            "points": [[0, 0], [100, 0]],
        }
    ]

    try:
        service_app.get_job_visual_evidence("job-a", request=_request_for_tenant("tenant-b"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected cross-tenant visual evidence lookup to fail")

    svg_response = service_app.get_job_visual_evidence_svg(
        "job-a",
        sheet_id="A101",
        source_page_index=1,
        request=_request_for_tenant("tenant-a"),
    )
    assert svg_response.media_type == "image/svg+xml"
    assert b"<svg" in svg_response.body
    assert b"Sheet A101" in svg_response.body

    preview = service_app.get_job_scale_calibration_preview(
        "job-a",
        sheet_id="A101",
        measured_pdf_units=50.0,
        known_length_ft=25.0,
        request=_request_for_tenant("tenant-a"),
    )
    assert preview["calibration"]["feet_per_pdf_unit"] == 0.5
    assert preview["preview"]["calibrated_vector_linework_total_ft"] == 50.0

    try:
        service_app.get_job_visual_evidence_svg(
            "job-a",
            sheet_id="A101",
            request=_request_for_tenant("tenant-b"),
        )
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected cross-tenant SVG lookup to fail")
