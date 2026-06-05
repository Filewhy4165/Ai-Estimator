from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_takeoff_line_items_payload(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    trade: str = "",
    quantity_name: str = "",
) -> dict[str, Any]:
    """Return reviewed takeoff line items with simple estimator-facing summaries."""
    items = _line_items_from_result(result)
    trade_filter = str(trade or "").strip().casefold()
    name_filter = str(quantity_name or "").strip().casefold()

    if trade_filter:
        items = [item for item in items if str(item.get("trade", "")).casefold() == trade_filter]
    if name_filter:
        items = [
            item
            for item in items
            if str(item.get("quantity_name", "")).casefold() == name_filter
        ]

    summary = _summarize_line_items(items)
    return {
        "job_id": job_id,
        "filters": {
            "trade": str(trade or "").strip(),
            "quantity_name": str(quantity_name or "").strip(),
        },
        "item_count": len(items),
        "summary": summary,
        "line_items": items,
    }


def _line_items_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    result = result if isinstance(result, dict) else {}
    takeoff = result.get("quantity_takeoff", {})
    if not isinstance(takeoff, dict):
        return []
    raw_items = takeoff.get("line_items", [])
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        normalized.append(
            {
                "line_item_id": str(raw.get("line_item_id") or f"line-{index}"),
                "source": str(raw.get("source", "")),
                "source_id": str(raw.get("source_id", "")),
                "label": str(raw.get("label", "")),
                "sheet_id": str(raw.get("sheet_id", "")),
                "source_page_index": raw.get("source_page_index"),
                "trade": str(raw.get("trade", "")),
                "quantity_bucket": str(raw.get("quantity_bucket", "linear") or "linear"),
                "quantity_name": str(raw.get("quantity_name", "line_item") or "line_item"),
                "description": str(raw.get("description", "")),
                "assembly": str(raw.get("assembly", "")),
                "cost_code": str(raw.get("cost_code", "")),
                "quantity": _numeric_or_none(raw.get("quantity")),
                "unit": str(raw.get("unit", "")),
                "known_length_ft": _numeric_or_none(raw.get("known_length_ft")),
                "measured_pdf_units": _numeric_or_none(raw.get("measured_pdf_units")),
            }
        )
    return normalized


def _summarize_line_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_by_unit: dict[str, float] = defaultdict(float)
    count_by_trade: dict[str, int] = defaultdict(int)
    total_by_trade_unit: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    total_by_name_unit: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for item in items:
        unit = str(item.get("unit", "")).strip() or "unknown"
        trade = str(item.get("trade", "")).strip() or "unknown"
        name = str(item.get("quantity_name", "")).strip() or "line_item"
        quantity = _numeric_or_none(item.get("quantity"))
        count_by_trade[trade] += 1
        if quantity is None:
            continue
        total_by_unit[unit] += quantity
        total_by_trade_unit[trade][unit] += quantity
        total_by_name_unit[name][unit] += quantity

    return {
        "total_by_unit": {key: round(value, 4) for key, value in sorted(total_by_unit.items())},
        "count_by_trade": dict(sorted(count_by_trade.items())),
        "total_by_trade_unit": {
            trade: {unit: round(value, 4) for unit, value in sorted(unit_values.items())}
            for trade, unit_values in sorted(total_by_trade_unit.items())
        },
        "total_by_name_unit": {
            name: {unit: round(value, 4) for unit, value in sorted(unit_values.items())}
            for name, unit_values in sorted(total_by_name_unit.items())
        },
    }


def _numeric_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
