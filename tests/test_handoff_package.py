from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from service.handoff_package import build_job_handoff_zip


def test_build_job_handoff_zip_contains_expected_files() -> None:
    payload = build_job_handoff_zip(
        job_id="job-1",
        status="completed",
        created_at="2026-06-01T00:00:00+00:00",
        updated_at="2026-06-01T00:01:00+00:00",
        completed_at="2026-06-01T00:02:00+00:00",
        input_payload={"analysis_mode": "all"},
        result={
            "quantity_takeoff": {"counts": {"door": 2}},
            "spec_context": {
                "applied_spec_profiles": [],
                "missing_from_drawings": [],
            },
        },
    )

    with ZipFile(BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        assert "job-1/README.txt" in names
        assert "job-1/job-record.json" in names
        assert "job-1/result.json" in names
        assert "job-1/takeoff.csv" in names
        assert "job-1/spec-compliance.json" in names
        assert "job-1/estimator-report.html" in names
        takeoff = archive.read("job-1/takeoff.csv").decode("utf-8")
        assert "door" in takeoff
        spec = json.loads(archive.read("job-1/spec-compliance.json").decode("utf-8"))
        assert spec["job_id"] == "job-1"
