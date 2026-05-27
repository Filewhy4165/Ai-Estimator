from __future__ import annotations

from ai_estimator.constants import TRADE_NAMES, TradeScope
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


CONFIDENCE_THRESHOLD_AUTO = 0.6


def resolve_trade_scope(
    sheets: list[ClassifiedSheet],
    requested_mode: str = "auto",
    requested_trades: list[str] | None = None,
) -> TradeScope:
    requested_trades = requested_trades or []
    requested_mode = requested_mode or "auto"
    collapsed_sheets = _collapse_sheets_for_scope(sheets)

    detected_trades = sorted({sheet.trade for sheet in collapsed_sheets if sheet.trade})
    if requested_mode not in {"auto", "selected", "all"}:
        requested_mode = "auto"

    analyzed_trades: list[str] = []
    skipped_trades: list[dict[str, str]] = []

    if requested_mode == "selected":
        normalized = [trade for trade in requested_trades if trade in TRADE_NAMES]
        analyzed_trades = sorted(set(normalized))
        for trade in detected_trades:
            if trade not in analyzed_trades:
                skipped_trades.append({"trade": trade, "reason": "Excluded by selected trade scope."})
    elif requested_mode == "all":
        analyzed_trades = detected_trades
    else:
        # Auto: include confident sheet-trade detections.
        trade_conf_map: dict[str, float] = {}
        for sheet in collapsed_sheets:
            current = trade_conf_map.get(sheet.trade, 0.0)
            trade_conf_map[sheet.trade] = max(current, sheet.confidence)

        analyzed_trades = sorted(
            [trade for trade, conf in trade_conf_map.items() if conf >= CONFIDENCE_THRESHOLD_AUTO]
        )
        for trade in detected_trades:
            if trade not in analyzed_trades:
                skipped_trades.append(
                    {"trade": trade, "reason": "Low confidence detection in auto mode."}
                )

    sheet_trade_map = [
        {"sheet": sheet.sheet_id, "trade": sheet.trade, "confidence": round(sheet.confidence, 3)}
        for sheet in collapsed_sheets
    ]

    return TradeScope(
        requested_mode=requested_mode,
        requested_trades=requested_trades,
        detected_trades=detected_trades,
        analyzed_trades=analyzed_trades,
        skipped_trades=skipped_trades,
        sheet_trade_map=sheet_trade_map,
    )


def _collapse_sheets_for_scope(sheets: list[ClassifiedSheet]) -> list[ClassifiedSheet]:
    by_sheet_trade: dict[tuple[str, str], ClassifiedSheet] = {}
    for sheet in sheets:
        key = (sheet.sheet_id, sheet.trade)
        existing = by_sheet_trade.get(key)
        if existing is None or sheet.confidence > existing.confidence:
            by_sheet_trade[key] = sheet
    return list(by_sheet_trade.values())
