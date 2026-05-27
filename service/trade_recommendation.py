from __future__ import annotations

from typing import Any


_SELECTED_THRESHOLD = 0.65
_HIGH_CONFIDENCE_THRESHOLD = 0.85


def build_trade_recommendation(
    *,
    job_id: str,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    trade_scope = result.get("trade_scope", {}) if isinstance(result, dict) else {}
    if not isinstance(trade_scope, dict):
        trade_scope = {}

    requested_mode = str(trade_scope.get("requested_mode", "auto")).strip() or "auto"
    requested_trades = _as_trade_list(trade_scope.get("requested_trades"))
    detected_trades = _as_trade_list(trade_scope.get("detected_trades"))
    sheet_trade_map = trade_scope.get("sheet_trade_map", [])

    score_rows = _build_trade_scores(detected_trades=detected_trades, sheet_trade_map=sheet_trade_map)
    score_by_trade = {row["trade"]: row for row in score_rows}
    candidate_selected = [
        row["trade"] for row in score_rows if isinstance(row.get("max_confidence"), float) and row["max_confidence"] >= _SELECTED_THRESHOLD
    ]
    low_conf_trades = [
        row["trade"] for row in score_rows if isinstance(row.get("max_confidence"), float) and row["max_confidence"] < _SELECTED_THRESHOLD
    ]

    uncertainty_ratio = 0.0
    if detected_trades:
        uncertainty_ratio = len(low_conf_trades) / len(detected_trades)

    if not detected_trades:
        recommended_mode = "all"
        recommended_trades: list[str] = []
        recommendation_reason = "No trades were detected from sheets; run all trades after sheet/title review."
    elif not candidate_selected:
        recommended_mode = "all"
        recommended_trades = detected_trades
        recommendation_reason = "All detected trades were low confidence; run all trades to reduce miss risk."
    elif uncertainty_ratio >= 0.4 and len(detected_trades) >= 3:
        recommended_mode = "all"
        recommended_trades = detected_trades
        recommendation_reason = "High uncertainty across detected trades; run all trades for safer coverage."
    else:
        recommended_mode = "selected"
        recommended_trades = candidate_selected
        recommendation_reason = "Detected trade confidence is stable; selected mode is sufficient."

    confidence = _compute_recommendation_confidence(
        recommended_mode=recommended_mode,
        recommended_trades=recommended_trades,
        detected_trades=detected_trades,
        score_by_trade=score_by_trade,
        uncertainty_ratio=uncertainty_ratio,
    )
    needs_user_review = recommended_mode == "all" and len(detected_trades) > 0

    rationale: list[str] = [
        f"Detected trades: {len(detected_trades)}.",
        f"Trades above confidence threshold {_SELECTED_THRESHOLD:.2f}: {len(candidate_selected)}.",
        recommendation_reason,
    ]
    if low_conf_trades:
        low_list = ", ".join(low_conf_trades[:5])
        rationale.append(f"Low-confidence trades: {low_list}.")
    if requested_mode != recommended_mode:
        rationale.append(f"Requested mode '{requested_mode}' differs from recommendation '{recommended_mode}'.")

    for row in score_rows:
        row["recommended"] = row["trade"] in recommended_trades
        if row["recommended"]:
            row["reason"] = "Included in recommendation."
        elif row["sheet_count"] == 0:
            row["reason"] = "No supporting sheets found."
        elif isinstance(row["max_confidence"], float) and row["max_confidence"] < _SELECTED_THRESHOLD:
            row["reason"] = "Below confidence threshold."
        else:
            row["reason"] = "Excluded by broader recommendation policy."

    return {
        "job_id": job_id,
        "requested_mode": requested_mode,
        "requested_trades": requested_trades,
        "detected_trades": detected_trades,
        "recommended_mode": recommended_mode,
        "recommended_trades": recommended_trades,
        "confidence": confidence,
        "needs_user_review": needs_user_review,
        "decision_rationale": rationale,
        "trade_scores": score_rows,
    }


def _build_trade_scores(*, detected_trades: list[str], sheet_trade_map: object) -> list[dict[str, Any]]:
    trade_confidences: dict[str, list[float]] = {trade: [] for trade in detected_trades}

    if isinstance(sheet_trade_map, list):
        for row in sheet_trade_map:
            if not isinstance(row, dict):
                continue
            trade = str(row.get("trade", "")).strip()
            if not trade:
                continue
            raw_conf = row.get("confidence")
            if isinstance(raw_conf, (int, float)):
                trade_confidences.setdefault(trade, []).append(float(raw_conf))
            else:
                trade_confidences.setdefault(trade, [])

    rows: list[dict[str, Any]] = []
    for trade in sorted(trade_confidences.keys()):
        values = trade_confidences[trade]
        sheet_count = len(values)
        if values:
            max_conf = round(max(values), 3)
            avg_conf = round(sum(values) / len(values), 3)
            if max_conf >= _HIGH_CONFIDENCE_THRESHOLD:
                band = "high"
            elif max_conf >= _SELECTED_THRESHOLD:
                band = "medium"
            else:
                band = "low"
        else:
            max_conf = None
            avg_conf = None
            band = "unknown"

        rows.append(
            {
                "trade": trade,
                "sheet_count": sheet_count,
                "max_confidence": max_conf,
                "avg_confidence": avg_conf,
                "confidence_band": band,
            }
        )
    return rows


def _as_trade_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        token = str(item).strip()
        if token:
            cleaned.append(token)
    return sorted(set(cleaned))


def _compute_recommendation_confidence(
    *,
    recommended_mode: str,
    recommended_trades: list[str],
    detected_trades: list[str],
    score_by_trade: dict[str, dict[str, Any]],
    uncertainty_ratio: float,
) -> float:
    anchor = recommended_trades if recommended_trades else detected_trades
    confidences: list[float] = []
    for trade in anchor:
        row = score_by_trade.get(trade)
        if not row:
            continue
        value = row.get("max_confidence")
        if isinstance(value, (int, float)):
            confidences.append(float(value))
    base = (sum(confidences) / len(confidences)) if confidences else 0.35
    confidence = base * (1.0 - (0.35 * max(0.0, min(1.0, uncertainty_ratio))))
    if recommended_mode == "all" and detected_trades:
        confidence *= 0.85
    return round(max(0.05, min(0.99, confidence)), 3)
