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
    result: dict | None = None,
    completed_at: str | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        created_at="2026-05-27T00:00:00+00:00",
        updated_at="2026-05-27T00:00:00+00:00",
        completed_at=completed_at,
        input={"analysis_mode": "auto", "selected_trades": []},
        queue_wait_seconds=queue_wait_seconds,
        run_duration_seconds=run_duration_seconds,
        result_sheet_count=result_sheet_count,
        result_issue_count=result_issue_count,
        result=result,
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
            completed_at="2026-05-27T00:59:30+00:00",
            result={
                "sheets_detected": [{"sheet_id": "A101"}, {"sheet_id": "UNMAPPED_1"}],
                "scale_analysis": {"by_sheet": [{"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\""}]},
                "legend_and_symbols": {"unknown_symbols": [{"symbol": "X1"}]},
            },
        ),
        _job(
            "job-2",
            status="failed",
            queue_wait_seconds=2.0,
            run_duration_seconds=10.0,
            result_sheet_count=0,
            result_issue_count=1,
            completed_at="2026-05-27T00:58:00+00:00",
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
    assert payload["active_jobs"] == 1
    assert payload["terminal_jobs"] == 2
    assert payload["failure_rate"] == 0.5
    assert payload["throughput_last_24h"]["terminal_jobs"] == 2
    assert payload["throughput_last_24h"]["completed_jobs"] == 1
    assert payload["throughput_last_24h"]["failed_jobs"] == 1
    assert payload["throughput_last_24h"]["jobs_per_hour"] == 0.083
    assert payload["queue_wait_seconds"]["count"] == 2
    assert payload["queue_wait_seconds"]["average"] == 2.5
    assert payload["run_duration_seconds"]["count"] == 2
    assert payload["run_duration_seconds"]["average"] == 33.5
    assert payload["result_sheet_count"]["maximum"] == 15.0
    assert payload["result_issue_count"]["maximum"] == 4.0
    assert payload["quality"]["completed_jobs_with_result"] == 1
    assert payload["quality"]["sheets_detected_total"] == 2
    assert payload["quality"]["unmapped_sheet_id_count"] == 1
    assert payload["quality"]["unmapped_sheet_id_rate"] == 0.5
    assert payload["quality"]["unknown_symbols_total"] == 1


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

    assert payload["active_jobs"] == 2
    assert payload["terminal_jobs"] == 0
    assert payload["failure_rate"] is None
    assert payload["throughput_last_24h"]["terminal_jobs"] == 0
    assert payload["queue_wait_seconds"]["count"] == 0
    assert payload["run_duration_seconds"]["count"] == 0
    assert payload["quality"]["completed_jobs_with_result"] == 0
