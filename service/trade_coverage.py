from __future__ import annotations

from typing import Any


_GEOMETRY_BUCKETS = ("walls", "doors", "windows", "slabs", "roofs", "fixtures", "equipment")


def build_trade_coverage_report(*, job_id: str, result: dict[str, Any] | None) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    trade_scope = payload.get("trade_scope", {})
    quantity_takeoff = payload.get("quantity_takeoff", {})
    geometry = payload.get("geometry", {})

    detected_trades = _as_trade_list(trade_scope.get("detected_trades")) if isinstance(trade_scope, dict) else []
    analyzed_trades = _as_trade_list(trade_scope.get("analyzed_trades")) if isinstance(trade_scope, dict) else []

    quantity_by_trade = quantity_takeoff.get("by_trade", {}) if isinstance(quantity_takeoff, dict) else {}
    geometry_counts = _geometry_counts_by_trade(geometry)
    quantity_counts = _quantity_counts_by_trade(quantity_by_trade)

    all_trades = sorted(set(detected_trades) | set(analyzed_trades) | set(geometry_counts.keys()) | set(quantity_counts.keys()))
    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {
        "covered": 0,
        "skipped": 0,
        "analyzed_no_signal": 0,
        "forced_selected": 0,
        "not_detected": 0,
    }
    needs_review: list[str] = []

    for trade in all_trades:
        detected = trade in detected_trades
        analyzed = trade in analyzed_trades
        geom_count = geometry_counts.get(trade, 0)
        qty_count = quantity_counts.get(trade, 0)
        signal_total = geom_count + qty_count

        if detected and not analyzed:
            status = "skipped"
        elif analyzed and signal_total == 0:
            status = "forced_selected" if not detected else "analyzed_no_signal"
        elif analyzed and signal_total > 0:
            status = "covered"
        else:
            status = "not_detected"

        status_counts[status] = status_counts.get(status, 0) + 1
        if status in {"skipped", "analyzed_no_signal"}:
            needs_review.append(trade)

        rows.append(
            {
                "trade": trade,
                "detected": detected,
                "analyzed": analyzed,
                "geometry_elements": geom_count,
                "quantity_counts_total": qty_count,
                "signal_total": signal_total,
                "status": status,
            }
        )

    summary = {
        "total_trades": len(rows),
        "detected_trades": len(detected_trades),
        "analyzed_trades": len(analyzed_trades),
        "status_counts": status_counts,
        "needs_review_count": len(needs_review),
    }

    return {
        "job_id": job_id,
        "summary": summary,
        "needs_review_trades": sorted(set(needs_review)),
        "trades": rows,
    }


def _geometry_counts_by_trade(geometry: object) -> dict[str, int]:
    if not isinstance(geometry, dict):
        return {}
    counts: dict[str, int] = {}
    for bucket in _GEOMETRY_BUCKETS:
        entries = geometry.get(bucket, [])
        if not isinstance(entries, list):
            continue
        for row in entries:
            if not isinstance(row, dict):
                continue
            trade = str(row.get("trade", "")).strip()
            if not trade:
                continue
            counts[trade] = counts.get(trade, 0) + 1
    return counts


def _quantity_counts_by_trade(quantity_by_trade: object) -> dict[str, int]:
    if not isinstance(quantity_by_trade, dict):
        return {}
    counts: dict[str, int] = {}
    for trade, payload in quantity_by_trade.items():
        if not isinstance(payload, dict):
            continue
        raw_counts = payload.get("counts", {})
        if not isinstance(raw_counts, dict):
            continue
        total = 0
        for value in raw_counts.values():
            if isinstance(value, (int, float)):
                total += int(value)
        counts[str(trade).strip()] = total
    return counts


def _as_trade_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        token = str(item).strip()
        if token:
            cleaned.append(token)
    return sorted(set(cleaned))
