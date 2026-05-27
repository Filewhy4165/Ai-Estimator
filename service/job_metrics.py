from __future__ import annotations

import math
from typing import Any

from service.job_store import JobRecord


_STATUS_KEYS = ("queued", "running", "completed", "failed")


def build_job_metrics_snapshot(
    records: list[JobRecord],
    *,
    window_requested: int,
    window_applied: int,
    generated_at: str,
) -> dict[str, Any]:
    status_counts = {key: 0 for key in _STATUS_KEYS}
    queue_waits: list[float] = []
    run_durations: list[float] = []
    sheet_counts: list[int] = []
    issue_counts: list[int] = []

    for record in records:
        status = str(record.status).strip().lower()
        if status in status_counts:
            status_counts[status] += 1

        if isinstance(record.queue_wait_seconds, (int, float)) and record.queue_wait_seconds >= 0:
            queue_waits.append(float(record.queue_wait_seconds))
        if isinstance(record.run_duration_seconds, (int, float)) and record.run_duration_seconds >= 0:
            run_durations.append(float(record.run_duration_seconds))
        if isinstance(record.result_sheet_count, int) and record.result_sheet_count >= 0:
            sheet_counts.append(record.result_sheet_count)
        if isinstance(record.result_issue_count, int) and record.result_issue_count >= 0:
            issue_counts.append(record.result_issue_count)

    terminal = status_counts["completed"] + status_counts["failed"]
    failure_rate = round(status_counts["failed"] / terminal, 4) if terminal > 0 else None

    return {
        "generated_at": generated_at,
        "window_requested": window_requested,
        "window_applied": window_applied,
        "jobs_considered": len(records),
        "status_counts": status_counts,
        "terminal_jobs": terminal,
        "failure_rate": failure_rate,
        "queue_wait_seconds": _distribution(queue_waits),
        "run_duration_seconds": _distribution(run_durations),
        "result_sheet_count": _distribution([float(value) for value in sheet_counts]),
        "result_issue_count": _distribution([float(value) for value in issue_counts]),
    }


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "average": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "minimum": None,
            "maximum": None,
        }

    ordered = sorted(values)
    average = sum(ordered) / len(ordered)
    return {
        "count": len(ordered),
        "average": round(average, 3),
        "p50": _percentile(ordered, 50),
        "p90": _percentile(ordered, 90),
        "p95": _percentile(ordered, 95),
        "minimum": round(ordered[0], 3),
        "maximum": round(ordered[-1], 3),
    }


def _percentile(values_sorted: list[float], percentile: int) -> float | None:
    if not values_sorted:
        return None
    if len(values_sorted) == 1:
        return round(values_sorted[0], 3)

    rank = (percentile / 100.0) * (len(values_sorted) - 1)
    low_index = int(math.floor(rank))
    high_index = int(math.ceil(rank))
    low_value = values_sorted[low_index]
    high_value = values_sorted[high_index]
    if low_index == high_index:
        return round(low_value, 3)
    weight = rank - low_index
    blended = (low_value * (1.0 - weight)) + (high_value * weight)
    return round(blended, 3)
