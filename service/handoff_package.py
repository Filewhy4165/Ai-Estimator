from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from service.job_report import build_job_report_html
from service.spec_report import build_spec_compliance_report
from service.takeoff_export import build_takeoff_csv


def build_job_handoff_zip(
    *,
    job_id: str,
    status: str,
    created_at: str,
    updated_at: str,
    completed_at: str | None,
    input_payload: dict[str, Any],
    result: dict[str, Any] | None,
) -> bytes:
    result = result if isinstance(result, dict) else {}
    input_payload = input_payload if isinstance(input_payload, dict) else {}
    safe_id = _safe_name(job_id)
    package = {
        "job_id": job_id,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
        "input": input_payload,
        "result": result,
    }
    spec_report = build_spec_compliance_report(job_id=job_id, result=result)
    html_report = build_job_report_html(
        job_id=job_id,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        completed_at=completed_at,
        input_payload=input_payload,
        result=result,
    )
    csv_text = build_takeoff_csv(job_id=job_id, result=result)
    readme = _readme_text(job_id=job_id, status=status)

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(f"{safe_id}/README.txt", readme)
        archive.writestr(f"{safe_id}/job-record.json", _json_dump(package))
        archive.writestr(f"{safe_id}/result.json", _json_dump(result))
        archive.writestr(f"{safe_id}/takeoff.csv", csv_text)
        archive.writestr(f"{safe_id}/spec-compliance.json", _json_dump(spec_report))
        archive.writestr(f"{safe_id}/estimator-report.html", html_report)
    return buffer.getvalue()


def _json_dump(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def _readme_text(*, job_id: str, status: str) -> str:
    return (
        "EstimateForge Job Handoff Package\n"
        "=================================\n\n"
        f"Job ID: {job_id}\n"
        f"Status: {status}\n\n"
        "Files:\n"
        "- estimator-report.html: readable estimator handoff report\n"
        "- takeoff.csv: Excel-friendly quantity rows\n"
        "- spec-compliance.json: applied specs, standards, and missing spec-required trades\n"
        "- result.json: structured estimator output\n"
        "- job-record.json: job metadata, input, and result payload\n\n"
        "Authority rule: drawings remain the highest authority, then specifications, then assumptions.\n"
    )


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return cleaned[:80] or "job"
