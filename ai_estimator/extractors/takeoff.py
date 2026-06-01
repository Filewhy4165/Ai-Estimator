from __future__ import annotations

from collections import defaultdict
import re


DIMENSION_VALUE_RE = re.compile(r"^\s*(\d+)\s*'\s*-\s*(\d+)\s*\"?\s*$")
IMPERIAL_SCALE_VALUE_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s*\"?\s*=\s*(\d+)\s*'\s*-\s*(\d+)\s*\"?\s*$",
    re.IGNORECASE,
)
METRIC_SCALE_VALUE_RE = re.compile(r"^\s*1\s*:\s*(\d+(?:\.\d+)?)\s*$", re.IGNORECASE)


def compute_quantity_takeoff(
    geometry: dict[str, object],
    scale_analysis: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[str]]:
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

    vector_linework = _compute_vector_linework_takeoff(geometry, scale_analysis=scale_analysis)
    if vector_linework["count"] > 0:
        linear["vector_linework_total_pdf_units"] = vector_linework["total_pdf_units"]
        linear["vector_linework_count"] = vector_linework["count"]
        linear["vector_linework_by_sheet_pdf_units"] = vector_linework["by_sheet_pdf_units"]
        if vector_linework["total_ft"] > 0:
            linear["vector_linework_total_ft"] = vector_linework["total_ft"]
            linear["vector_linework_by_sheet_ft"] = vector_linework["by_sheet_ft"]
        issues.append(
            "Vector linework was measured from PDF drawing geometry. Treat it as review evidence, "
            "not installed quantity, until classified by trade and checked against scale."
        )
        unscaled_sheets = vector_linework.get("unscaled_sheets", [])
        if isinstance(unscaled_sheets, list) and unscaled_sheets:
            issues.append(
                "Vector linework could not be converted to feet for sheets without a measurable scale: "
                + ", ".join(str(item) for item in unscaled_sheets[:20])
                + "."
            )
        by_trade_vector = vector_linework["by_trade"]
        if isinstance(by_trade_vector, dict):
            for trade, trade_values in by_trade_vector.items():
                if not isinstance(trade_values, dict):
                    continue
                by_trade[trade]["linear"]["vector_linework_total_pdf_units"] = trade_values.get(
                    "total_pdf_units", 0.0
                )
                by_trade[trade]["linear"]["vector_linework_count"] = trade_values.get("count", 0)
                if float(trade_values.get("total_ft", 0.0) or 0.0) > 0:
                    by_trade[trade]["linear"]["vector_linework_total_ft"] = trade_values.get(
                        "total_ft", 0.0
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


def _compute_vector_linework_takeoff(
    geometry: dict[str, object],
    *,
    scale_analysis: dict[str, object] | None,
) -> dict[str, object]:
    annotations = geometry.get("annotations", {})
    if not isinstance(annotations, dict):
        return _empty_vector_takeoff()
    measurements = annotations.get("vector_measurements", [])
    if not isinstance(measurements, list):
        return _empty_vector_takeoff()

    feet_per_pdf_unit_by_sheet = _scale_feet_per_pdf_unit_by_sheet(scale_analysis)
    count = 0
    total_pdf_units = 0.0
    total_ft = 0.0
    by_sheet_pdf_units: dict[str, float] = defaultdict(float)
    by_sheet_ft: dict[str, float] = defaultdict(float)
    by_trade: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"total_pdf_units": 0.0, "total_ft": 0.0, "count": 0}
    )
    unscaled_sheets: set[str] = set()

    for row in measurements:
        if not isinstance(row, dict):
            continue
        length = _numeric(row.get("total_linework_pdf_units"))
        if length <= 0:
            continue
        sheet_id = str(row.get("sheet_id", "unknown")).strip() or "unknown"
        trade = str(row.get("trade", "other")).strip() or "other"
        primitive_count = int(_numeric(row.get("line_count")) + _numeric(row.get("rectangle_count")))
        count += max(primitive_count, 1)
        total_pdf_units += length
        by_sheet_pdf_units[sheet_id] += length
        by_trade[trade]["total_pdf_units"] = float(by_trade[trade]["total_pdf_units"]) + length
        by_trade[trade]["count"] = int(by_trade[trade]["count"]) + max(primitive_count, 1)

        feet_per_pdf_unit = feet_per_pdf_unit_by_sheet.get(sheet_id)
        if feet_per_pdf_unit is None:
            unscaled_sheets.add(sheet_id)
            continue
        scaled_ft = length * feet_per_pdf_unit
        total_ft += scaled_ft
        by_sheet_ft[sheet_id] += scaled_ft
        by_trade[trade]["total_ft"] = float(by_trade[trade]["total_ft"]) + scaled_ft

    return {
        "count": count,
        "total_pdf_units": round(total_pdf_units, 4),
        "total_ft": round(total_ft, 4),
        "by_sheet_pdf_units": {
            key: round(value, 4) for key, value in sorted(by_sheet_pdf_units.items())
        },
        "by_sheet_ft": {key: round(value, 4) for key, value in sorted(by_sheet_ft.items())},
        "by_trade": {
            key: {
                "total_pdf_units": round(float(value.get("total_pdf_units", 0.0)), 4),
                "total_ft": round(float(value.get("total_ft", 0.0)), 4),
                "count": int(value.get("count", 0)),
            }
            for key, value in sorted(by_trade.items())
        },
        "unscaled_sheets": sorted(unscaled_sheets),
    }


def _empty_vector_takeoff() -> dict[str, object]:
    return {
        "count": 0,
        "total_pdf_units": 0.0,
        "total_ft": 0.0,
        "by_sheet_pdf_units": {},
        "by_sheet_ft": {},
        "by_trade": {},
        "unscaled_sheets": [],
    }


def _scale_feet_per_pdf_unit_by_sheet(
    scale_analysis: dict[str, object] | None,
) -> dict[str, float]:
    if not isinstance(scale_analysis, dict):
        return {}
    rows = scale_analysis.get("by_sheet", [])
    if not isinstance(rows, list):
        return {}

    by_sheet: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sheet_id = str(row.get("sheet_id", "")).strip()
        scale_value = str(row.get("detected_scale", "")).strip()
        units = str(row.get("units", "")).strip().lower()
        if not sheet_id or not scale_value or scale_value.upper() == "NTS":
            continue
        feet_per_pdf_unit: float | None = None
        if units == "imperial":
            feet_per_pdf_unit = _imperial_scale_feet_per_pdf_unit(scale_value)
        elif units == "metric":
            feet_per_pdf_unit = _metric_scale_feet_per_pdf_unit(scale_value)
        if feet_per_pdf_unit is not None and feet_per_pdf_unit > 0:
            by_sheet[sheet_id] = feet_per_pdf_unit
    return by_sheet


def _imperial_scale_feet_per_pdf_unit(scale_value: str) -> float | None:
    match = IMPERIAL_SCALE_VALUE_RE.match(scale_value)
    if not match:
        return None
    paper_inches = _parse_number_or_fraction(match.group(1))
    real_feet = int(match.group(2)) + (int(match.group(3)) / 12.0)
    if paper_inches <= 0 or real_feet <= 0:
        return None
    return (real_feet / paper_inches) / 72.0


def _metric_scale_feet_per_pdf_unit(scale_value: str) -> float | None:
    match = METRIC_SCALE_VALUE_RE.match(scale_value)
    if not match:
        return None
    ratio = float(match.group(1))
    if ratio <= 0:
        return None
    # PDF user units are normally points. 1 pt = 25.4 / 72 mm.
    real_meters_per_pdf_unit = ((25.4 / 72.0) * ratio) / 1000.0
    return real_meters_per_pdf_unit * 3.280839895


def _parse_number_or_fraction(value: str) -> float:
    token = "".join(value.split())
    if "/" in token:
        numerator, denominator = token.split("/", 1)
        denom = float(denominator)
        if denom == 0:
            return 0.0
        return float(numerator) / denom
    return float(token)


def _numeric(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0
