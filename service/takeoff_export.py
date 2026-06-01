from __future__ import annotations

import csv
from io import StringIO
from typing import Any


CSV_COLUMNS = [
    "job_id",
    "scope",
    "trade",
    "quantity_bucket",
    "quantity_name",
    "value",
    "unit_hint",
    "source",
]


def build_takeoff_csv(*, job_id: str, result: dict[str, Any] | None) -> str:
    """Build a cost-handoff CSV from the quantity_takeoff payload."""
    rows = build_takeoff_rows(job_id=job_id, result=result)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def build_takeoff_rows(*, job_id: str, result: dict[str, Any] | None) -> list[dict[str, str]]:
    result = result or {}
    quantity_takeoff = result.get("quantity_takeoff", {})
    if not isinstance(quantity_takeoff, dict):
        return []

    rows: list[dict[str, str]] = []
    for bucket in ("linear", "area", "volume", "counts"):
        values = quantity_takeoff.get(bucket, {})
        if isinstance(values, dict):
            rows.extend(
                _flatten_quantity_dict(
                    job_id=job_id,
                    scope="overall",
                    trade="",
                    bucket=bucket,
                    values=values,
                    source="quantity_takeoff",
                )
            )

    by_trade = quantity_takeoff.get("by_trade", {})
    if isinstance(by_trade, dict):
        for trade, trade_payload in sorted(by_trade.items(), key=lambda item: str(item[0]).casefold()):
            if not isinstance(trade_payload, dict):
                continue
            for bucket in ("linear", "area", "volume", "counts"):
                values = trade_payload.get(bucket, {})
                if isinstance(values, dict):
                    rows.extend(
                        _flatten_quantity_dict(
                            job_id=job_id,
                            scope="trade",
                            trade=str(trade),
                            bucket=bucket,
                            values=values,
                            source="quantity_takeoff.by_trade",
                        )
                    )

    cost_mapping = result.get("cost_mapping", {})
    if isinstance(cost_mapping, dict):
        cost_codes = cost_mapping.get("cost_codes", {})
        if isinstance(cost_codes, dict):
            rows.extend(_cost_code_rows(job_id=job_id, cost_codes=cost_codes))

    return rows


def _flatten_quantity_dict(
    *,
    job_id: str,
    scope: str,
    trade: str,
    bucket: str,
    values: dict[str, Any],
    source: str,
    prefix: str = "",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, value in sorted(values.items(), key=lambda item: str(item[0]).casefold()):
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rows.extend(
                _flatten_quantity_dict(
                    job_id=job_id,
                    scope=scope,
                    trade=trade,
                    bucket=bucket,
                    values=value,
                    source=source,
                    prefix=name,
                )
            )
            continue
        if isinstance(value, list):
            value_text = "; ".join(str(item) for item in value)
        else:
            value_text = str(value)
        rows.append(
            {
                "job_id": job_id,
                "scope": scope,
                "trade": trade,
                "quantity_bucket": bucket,
                "quantity_name": name,
                "value": value_text,
                "unit_hint": _unit_hint(bucket=bucket, name=name),
                "source": source,
            }
        )
    return rows


def _cost_code_rows(*, job_id: str, cost_codes: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    csi = cost_codes.get("csi_masterformat", {})
    if isinstance(csi, dict):
        for trade, codes in sorted(csi.items(), key=lambda item: str(item[0]).casefold()):
            if isinstance(codes, list):
                value_text = "; ".join(str(code) for code in codes)
            else:
                value_text = str(codes)
            rows.append(
                {
                    "job_id": job_id,
                    "scope": "trade",
                    "trade": str(trade),
                    "quantity_bucket": "cost_codes",
                    "quantity_name": "csi_masterformat",
                    "value": value_text,
                    "unit_hint": "code",
                    "source": "cost_mapping.cost_codes",
                }
            )
    return rows


def _unit_hint(*, bucket: str, name: str) -> str:
    lowered = name.lower()
    if bucket == "linear" or lowered.endswith("_ft") or "_ft." in lowered:
        return "ft"
    if bucket == "area" or "sf" in lowered or "sqft" in lowered:
        return "sf"
    if bucket == "volume" or "cy" in lowered:
        return "cy"
    if bucket == "counts" or lowered.endswith("_count") or lowered == "count":
        return "count"
    if "pdf_units" in lowered:
        return "pdf_units"
    return ""
