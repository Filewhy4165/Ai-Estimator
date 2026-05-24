from __future__ import annotations

from ai_estimator.constants import DEFAULT_CSI_BY_TRADE


def map_costs(quantity_takeoff: dict[str, object]) -> dict[str, object]:
    by_trade = quantity_takeoff.get("by_trade", {})
    assemblies: dict[str, object] = {}
    csi_masterformat: dict[str, object] = {}
    contractor_custom: dict[str, object] = {}

    if isinstance(by_trade, dict):
        for trade, buckets in by_trade.items():
            counts = {}
            if isinstance(buckets, dict):
                counts = buckets.get("counts", {})

            assemblies[trade] = {
                "derived_from_counts": counts,
                "note": "Placeholder assembly mapping. Replace with estimator-specific recipes.",
            }
            csi_masterformat[trade] = DEFAULT_CSI_BY_TRADE.get(trade, [])
            contractor_custom[trade] = {}

    return {
        "assemblies": assemblies,
        "cost_codes": {
            "csi_masterformat": csi_masterformat,
            "contractor_custom": contractor_custom,
        },
    }

