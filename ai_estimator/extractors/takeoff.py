from __future__ import annotations

from collections import defaultdict
import re


DIMENSION_VALUE_RE = re.compile(r"^\s*(\d+)\s*'\s*-\s*(\d+)\s*\"?\s*$")


def compute_quantity_takeoff(geometry: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    by_trade: dict[str, dict[str, object]] = defaultdict(
        lambda: {"linear": {}, "area": {}, "volume": {}, "counts": {}}
    )
    counts: dict[str, int] = defaultdict(int)

    for bucket in ("walls", "doors", "windows", "slabs", "roofs", "fixtures", "equipment"):
        items = geometry.get(bucket, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            trade = str(item.get("trade", "other"))
            element_type = str(item.get("type", bucket.rstrip("s")))
            by_trade[trade]["counts"][element_type] = by_trade[trade]["counts"].get(element_type, 0) + 1
            counts[element_type] += 1

    if not counts:
        issues.append(
            "No quantity counts could be computed because measurable elements were not extracted."
        )

    # Conservative defaults for units that require geometry dimensions.
    linear: dict[str, object] = {}
    area: dict[str, object] = {}
    volume: dict[str, object] = {}
    explicit_dimensions = _compute_explicit_dimension_takeoff(geometry)
    if explicit_dimensions["count"] > 0:
        linear["explicit_dimensions_total_ft"] = explicit_dimensions["total_ft"]
        linear["explicit_dimensions_count"] = explicit_dimensions["count"]
        linear["explicit_dimensions_by_sheet_ft"] = explicit_dimensions["by_sheet"]
        issues.append(
            "Explicit drawing dimensions were captured as reference linear measurements. "
            "They are not installed quantities until tied to detected geometry or a reviewed assembly."
        )
        by_trade_dimensions = explicit_dimensions["by_trade"]
        if isinstance(by_trade_dimensions, dict):
            for trade, trade_values in by_trade_dimensions.items():
                if not isinstance(trade_values, dict):
                    continue
                by_trade[trade]["linear"]["explicit_dimensions_total_ft"] = trade_values.get(
                    "total_ft", 0.0
                )
                by_trade[trade]["linear"]["explicit_dimensions_count"] = trade_values.get(
                    "count", 0
                )

    if not linear:
        issues.append("Linear quantities are empty; no reliable lengths were extracted.")
    if not area:
        issues.append("Area quantities are empty; no reliable surface boundaries were extracted.")
    if not volume:
        issues.append("Volume quantities are empty; no reliable volumetric geometry was extracted.")

    return (
        {
            "by_trade": dict(by_trade),
            "linear": linear,
            "area": area,
            "volume": volume,
            "counts": dict(counts),
        },
        issues,
    )


def _compute_explicit_dimension_takeoff(geometry: dict[str, object]) -> dict[str, object]:
    annotations = geometry.get("annotations", {})
    if not isinstance(annotations, dict):
        return {"count": 0, "total_ft": 0.0, "by_sheet": {}, "by_trade": {}}

    dimensions = annotations.get("dimensions", [])
    if not isinstance(dimensions, list):
        return {"count": 0, "total_ft": 0.0, "by_sheet": {}, "by_trade": {}}

    count = 0
    total_ft = 0.0
    by_sheet: dict[str, float] = defaultdict(float)
    by_trade: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"total_ft": 0.0, "count": 0}
    )

    for row in dimensions:
        if not isinstance(row, dict):
            continue
        value = str(row.get("value", "")).strip()
        parsed = _dimension_to_feet(value)
        if parsed is None:
            continue
        count += 1
        total_ft += parsed
        sheet_id = str(row.get("sheet_id", "unknown")).strip() or "unknown"
        trade = str(row.get("trade", "other")).strip() or "other"
        by_sheet[sheet_id] += parsed
        by_trade[trade]["total_ft"] = float(by_trade[trade]["total_ft"]) + parsed
        by_trade[trade]["count"] = int(by_trade[trade]["count"]) + 1

    return {
        "count": count,
        "total_ft": round(total_ft, 4),
        "by_sheet": {key: round(value, 4) for key, value in sorted(by_sheet.items())},
        "by_trade": {
            key: {
                "total_ft": round(float(value.get("total_ft", 0.0)), 4),
                "count": int(value.get("count", 0)),
            }
            for key, value in sorted(by_trade.items())
        },
    }


def _dimension_to_feet(value: str) -> float | None:
    match = DIMENSION_VALUE_RE.match(value)
    if not match:
        return None
    feet = int(match.group(1))
    inches = int(match.group(2))
    if inches >= 12:
        return None
    return feet + (inches / 12.0)
