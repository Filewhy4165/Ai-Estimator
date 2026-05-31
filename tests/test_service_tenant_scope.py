from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

import service.app as service_app
from service.job_store import JobRecord, JobStore


def _record(job_id: str, *, status: str, tenant_id: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        tenant_id=tenant_id,
        status=status,
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
    )


def _request_for_tenant(tenant_id: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/jobs",
            "query_string": b"",
            "headers": [(b"x-tenant-id", tenant_id.encode("utf-8"))],
        }
    )


def test_list_and_get_jobs_are_scoped_by_tenant(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-a", status="completed", tenant_id="tenant-a"))
    store.create_job(_record("job-b", status="completed", tenant_id="tenant-b"))
    monkeypatch.setattr(service_app, "_job_store", store)

    request_a = _request_for_tenant("tenant-a")
    payload = service_app.list_jobs(request=request_a).model_dump()
    assert payload["total_returned"] == 1
    assert payload["items"][0]["job_id"] == "job-a"
    assert payload["items"][0]["tenant_id"] == "tenant-a"

    record = service_app.get_job("job-a", request=request_a)
    assert record["job_id"] == "job-a"
    assert record["tenant_id"] == "tenant-a"

    try:
        service_app.get_job("job-b", request=request_a)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected cross-tenant lookup to return HTTPException(404)")


def test_delete_job_is_scoped_by_tenant(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-b", status="completed", tenant_id="tenant-b"))
    monkeypatch.setattr(service_app, "_job_store", store)

    request_a = _request_for_tenant("tenant-a")
    request_b = _request_for_tenant("tenant-b")

    try:
        service_app.delete_job("job-b", request=request_a)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected cross-tenant delete to return HTTPException(404)")

    payload = service_app.delete_job("job-b", request=request_b).model_dump()
    assert payload["deleted"] is True
    assert store.get_job("job-b", tenant_id="tenant-b") is None


def test_capacity_counts_are_scoped_by_tenant(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-a-run", status="running", tenant_id="tenant-a"))
    store.create_job(_record("job-b-queue", status="queued", tenant_id="tenant-b"))
    monkeypatch.setattr(service_app, "_job_store", store)

    capacity_a = service_app.get_job_capacity(request=_request_for_tenant("tenant-a")).model_dump()
    capacity_b = service_app.get_job_capacity(request=_request_for_tenant("tenant-b")).model_dump()

    assert capacity_a["running_jobs"] == 1
    assert capacity_a["queued_jobs"] == 0
    assert capacity_b["running_jobs"] == 0
    assert capacity_b["queued_jobs"] == 1


def test_invalid_tenant_header_rejected(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    store.create_job(_record("job-a", status="completed", tenant_id="tenant-a"))
    monkeypatch.setattr(service_app, "_job_store", store)

    bad_request = _request_for_tenant("invalid tenant")
    try:
        service_app.list_jobs(request=bad_request)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected invalid tenant header to return HTTPException(400)")
