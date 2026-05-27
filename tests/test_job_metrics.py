from __future__ import annotations

from service.job_metrics import build_job_metrics_snapshot
from service.job_store import JobRecord


def _job(
    job_id: str,
    *,
    status: str,
    queue_wait_seconds: float | None = None,
    run_duration_seconds: float | None = None,
    result_sheet_count: int | None = None,
    result_issue_count: int | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
        queue_wait_seconds=queue_wait_seconds,
        run_duration_seconds=run_duration_seconds,
        result_sheet_count=result_sheet_count,
        result_issue_count=result_issue_count,
    )


def test_build_job_metrics_snapshot_with_terminal_jobs():
    records = [
        _job(
            "job-1",
            status="completed",
            queue_wait_seconds=3.0,
            run_duration_seconds=57.0,
            result_sheet_count=15,
            result_issue_count=4,
        ),
        _job(
            "job-2",
            status="failed",
            queue_wait_seconds=2.0,
            run_duration_seconds=10.0,
            result_sheet_count=0,
            result_issue_count=1,
        ),
        _job("job-3", status="running"),
    ]
    payload = build_job_metrics_snapshot(
        records,
        window_requested=500,
        window_applied=500,
        generated_at="2026-05-27T01:00:00+00:00",
    )

    assert payload["jobs_considered"] == 3
    assert payload["status_counts"] == {
        "queued": 0,
        "running": 1,
        "completed": 1,
        "failed": 1,
    }
    assert payload["terminal_jobs"] == 2
    assert payload["failure_rate"] == 0.5
    assert payload["queue_wait_seconds"]["count"] == 2
    assert payload["queue_wait_seconds"]["average"] == 2.5
    assert payload["run_duration_seconds"]["count"] == 2
    assert payload["run_duration_seconds"]["average"] == 33.5
    assert payload["result_sheet_count"]["maximum"] == 15.0
    assert payload["result_issue_count"]["maximum"] == 4.0


def test_build_job_metrics_snapshot_without_terminal_jobs():
    records = [
        _job("job-1", status="queued"),
        _job("job-2", status="running"),
    ]
    payload = build_job_metrics_snapshot(
        records,
        window_requested=200,
        window_applied=200,
        generated_at="2026-05-27T01:00:00+00:00",
    )

    assert payload["terminal_jobs"] == 0
    assert payload["failure_rate"] is None
    assert payload["queue_wait_seconds"]["count"] == 0
    assert payload["run_duration_seconds"]["count"] == 0
