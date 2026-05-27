from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from service.job_store import JobRecord


_STATUS_KEYS = ("queued", "running", "completed", "failed", "canceled")


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
    completed_jobs_with_result = 0
    sheets_detected_total = 0
    unmapped_sheet_id_count = 0
    scale_rows_total = 0
    missing_scale_count = 0
    nts_scale_count = 0
    unknown_symbols_total = 0
    completed_24h = 0
    failed_24h = 0
    canceled_24h = 0
    generated_dt = _parse_iso_datetime(generated_at) or datetime.now(timezone.utc)
    throughput_start = generated_dt - timedelta(hours=24)

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

        if status in {"completed", "failed", "canceled"}:
            terminal_at = _parse_iso_datetime(record.completed_at) or _parse_iso_datetime(record.updated_at)
            if terminal_at and throughput_start <= terminal_at <= generated_dt:
                if status == "completed":
                    completed_24h += 1
                elif status == "canceled":
                    canceled_24h += 1
                else:
                    failed_24h += 1

        result_payload = record.result if isinstance(record.result, dict) else None
        if status != "completed" or result_payload is None:
            continue
        completed_jobs_with_result += 1

        sheets = result_payload.get("sheets_detected", [])
        if isinstance(sheets, list):
            sheets_detected_total += len(sheets)
            for row in sheets:
                if not isinstance(row, dict):
                    continue
                sheet_id = str(row.get("sheet_id", "")).strip()
                if sheet_id.startswith("UNMAPPED_"):
                    unmapped_sheet_id_count += 1

        scale_analysis = result_payload.get("scale_analysis", {})
        if isinstance(scale_analysis, dict):
            scale_rows = scale_analysis.get("by_sheet", [])
            if isinstance(scale_rows, list):
                scale_rows_total += len(scale_rows)
                for row in scale_rows:
                    if not isinstance(row, dict):
                        missing_scale_count += 1
                        continue
                    raw_scale = row.get("detected_scale")
                    if raw_scale is None or not str(raw_scale).strip():
                        missing_scale_count += 1
                        continue
                    if str(raw_scale).strip().upper() == "NTS":
                        nts_scale_count += 1

        legend = result_payload.get("legend_and_symbols", {})
        if isinstance(legend, dict):
            unknown_symbols = legend.get("unknown_symbols", [])
            if isinstance(unknown_symbols, list):
                unknown_symbols_total += len(unknown_symbols)

    completed_or_failed = status_counts["completed"] + status_counts["failed"]
    terminal = completed_or_failed + status_counts["canceled"]
    failure_rate = round(status_counts["failed"] / completed_or_failed, 4) if completed_or_failed > 0 else None
    terminal_24h = completed_24h + failed_24h + canceled_24h

    return {
        "generated_at": generated_at,
        "window_requested": window_requested,
        "window_applied": window_applied,
        "jobs_considered": len(records),
        "status_counts": status_counts,
        "active_jobs": status_counts["queued"] + status_counts["running"],
        "terminal_jobs": terminal,
        "failure_rate": failure_rate,
        "throughput_last_24h": {
            "terminal_jobs": terminal_24h,
            "completed_jobs": completed_24h,
            "failed_jobs": failed_24h,
            "canceled_jobs": canceled_24h,
            "jobs_per_hour": round(terminal_24h / 24.0, 3),
        },
        "queue_wait_seconds": _distribution(queue_waits),
        "run_duration_seconds": _distribution(run_durations),
        "result_sheet_count": _distribution([float(value) for value in sheet_counts]),
        "result_issue_count": _distribution([float(value) for value in issue_counts]),
        "quality": {
            "completed_jobs_with_result": completed_jobs_with_result,
            "sheets_detected_total": sheets_detected_total,
            "unmapped_sheet_id_count": unmapped_sheet_id_count,
            "unmapped_sheet_id_rate": _ratio(unmapped_sheet_id_count, sheets_detected_total),
            "scale_rows_total": scale_rows_total,
            "missing_scale_count": missing_scale_count,
            "missing_scale_rate": _ratio(missing_scale_count, scale_rows_total),
            "nts_scale_count": nts_scale_count,
            "nts_scale_rate": _ratio(nts_scale_count, scale_rows_total),
            "unknown_symbols_total": unknown_symbols_total,
            "unknown_symbols_per_completed_job": _ratio(
                unknown_symbols_total, completed_jobs_with_result
            ),
        },
    }


def evaluate_job_metrics_gate(
    snapshot: dict[str, Any],
    *,
    max_failure_rate: float | None = None,
    max_active_jobs: int | None = None,
    max_missing_scale_rate: float | None = None,
    max_unmapped_sheet_rate: float | None = None,
    min_jobs_per_hour_24h: float | None = None,
) -> dict[str, Any]:
    thresholds = {
        "max_failure_rate": max_failure_rate,
        "max_active_jobs": max_active_jobs,
        "max_missing_scale_rate": max_missing_scale_rate,
        "max_unmapped_sheet_rate": max_unmapped_sheet_rate,
        "min_jobs_per_hour_24h": min_jobs_per_hour_24h,
    }
    failures: list[dict[str, Any]] = []

    actual_failure_rate = _safe_float(snapshot.get("failure_rate"))
    if max_failure_rate is not None and actual_failure_rate is not None and actual_failure_rate > max_failure_rate:
        failures.append(
            {
                "code": "failure_rate_exceeded",
                "message": "Failure rate is above threshold.",
                "actual": actual_failure_rate,
                "threshold": max_failure_rate,
            }
        )

    actual_active_jobs = _safe_int(snapshot.get("active_jobs"))
    if max_active_jobs is not None and actual_active_jobs is not None and actual_active_jobs > max_active_jobs:
        failures.append(
            {
                "code": "active_jobs_exceeded",
                "message": "Active jobs exceed threshold.",
                "actual": actual_active_jobs,
                "threshold": max_active_jobs,
            }
        )

    quality = snapshot.get("quality", {})
    actual_missing_scale_rate = _safe_float(quality.get("missing_scale_rate")) if isinstance(quality, dict) else None
    if (
        max_missing_scale_rate is not None
        and actual_missing_scale_rate is not None
        and actual_missing_scale_rate > max_missing_scale_rate
    ):
        failures.append(
            {
                "code": "missing_scale_rate_exceeded",
                "message": "Missing-scale rate is above threshold.",
                "actual": actual_missing_scale_rate,
                "threshold": max_missing_scale_rate,
            }
        )

    actual_unmapped_sheet_rate = (
        _safe_float(quality.get("unmapped_sheet_id_rate")) if isinstance(quality, dict) else None
    )
    if (
        max_unmapped_sheet_rate is not None
        and actual_unmapped_sheet_rate is not None
        and actual_unmapped_sheet_rate > max_unmapped_sheet_rate
    ):
        failures.append(
            {
                "code": "unmapped_sheet_rate_exceeded",
                "message": "Unmapped-sheet rate is above threshold.",
                "actual": actual_unmapped_sheet_rate,
                "threshold": max_unmapped_sheet_rate,
            }
        )

    throughput = snapshot.get("throughput_last_24h", {})
    actual_jobs_per_hour = _safe_float(throughput.get("jobs_per_hour")) if isinstance(throughput, dict) else None
    if (
        min_jobs_per_hour_24h is not None
        and actual_jobs_per_hour is not None
        and actual_jobs_per_hour < min_jobs_per_hour_24h
    ):
        failures.append(
            {
                "code": "throughput_below_minimum",
                "message": "24h throughput is below minimum threshold.",
                "actual": actual_jobs_per_hour,
                "threshold": min_jobs_per_hour_24h,
            }
        )

    return {
        "passed": len(failures) == 0,
        "thresholds": thresholds,
        "actual": {
            "failure_rate": actual_failure_rate,
            "active_jobs": actual_active_jobs,
            "missing_scale_rate": actual_missing_scale_rate,
            "unmapped_sheet_rate": actual_unmapped_sheet_rate,
            "jobs_per_hour_24h": actual_jobs_per_hour,
        },
        "failures": failures,
        "snapshot": snapshot,
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


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    token = str(value).strip()
    if not token:
        return None
    try:
        parsed = datetime.fromisoformat(token)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None
