from __future__ import annotations

from collections import defaultdict


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

