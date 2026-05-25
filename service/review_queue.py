from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any


SHEET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]{0,79}$")


def build_review_queue(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    low_confidence_threshold: float = 0.75,
    include_only_flagged: bool = True,
) -> dict[str, Any]:
    result = result or {}
    sheets = result.get("sheets_detected", [])
    if not isinstance(sheets, list):
        sheets = []

    unknown_symbols = (
        result.get("legend_and_symbols", {}).get("unknown_symbols", [])
        if isinstance(result.get("legend_and_symbols", {}), dict)
        else []
    )
    unknown_counts = _count_unknown_symbols_by_sheet(unknown_symbols)
    scale_status = _sheet_scale_status(result.get("scale_analysis", {}))

    items: list[dict[str, Any]] = []
    reasons_counter: Counter[str] = Counter()

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        sheet_id = str(sheet.get("sheet_id", "")).strip()
        title = str(sheet.get("title", "")).strip()
        confidence = float(sheet.get("confidence", 0.0) or 0.0)
        source_page_index = sheet.get("source_page_index")

        reasons: list[dict[str, str]] = []
        if sheet_id.startswith("UNMAPPED_"):
            reasons.append(
                _reason(
                    code="unmapped_sheet_id",
                    severity="high",
                    message="Sheet ID could not be confidently detected.",
                )
            )
        elif not _is_reasonable_sheet_id(sheet_id):
            reasons.append(
                _reason(
                    code="invalid_sheet_id_format",
                    severity="medium",
                    message="Sheet ID format looks unusual. Review manually.",
                )
            )

        if confidence < low_confidence_threshold:
            reasons.append(
                _reason(
                    code="low_confidence_classification",
                    severity="medium",
                    message=f"Sheet confidence {confidence:.2f} is below threshold {low_confidence_threshold:.2f}.",
                )
            )

        scale = scale_status.get(sheet_id, {"has_scale": False, "only_nts": False})
        if not scale["has_scale"]:
            reasons.append(
                _reason(
                    code="missing_scale",
                    severity="high",
                    message="No measurable drawing scale detected for this sheet.",
                )
            )
        elif scale["only_nts"]:
            reasons.append(
                _reason(
                    code="nts_scale",
                    severity="medium",
                    message="Sheet appears marked NTS; quantitative measurements may be unreliable.",
                )
            )

        symbol_count = unknown_counts.get(sheet_id, 0)
        if symbol_count >= 10:
            reasons.append(
                _reason(
                    code="high_unknown_symbol_count",
                    severity="medium",
                    message=f"{symbol_count} unclassified symbols detected.",
                )
            )
        elif symbol_count > 0:
            reasons.append(
                _reason(
                    code="unknown_symbols_present",
                    severity="low",
                    message=f"{symbol_count} unclassified symbols detected.",
                )
            )

        if title in {"Untitled Sheet", ""}:
            reasons.append(
                _reason(
                    code="missing_sheet_title",
                    severity="low",
                    message="Sheet title was not confidently extracted.",
                )
            )

        for r in reasons:
            reasons_counter[r["code"]] += 1

        item = {
            "sheet_id": sheet_id,
            "title": title,
            "confidence": round(confidence, 3),
            "source_page_index": source_page_index,
            "discipline": sheet.get("discipline"),
            "unknown_symbol_count": symbol_count,
            "flags": reasons,
        }
        if not include_only_flagged or reasons:
            items.append(item)

    items.sort(key=lambda item: _item_sort_key(item))

    return {
        "job_id": job_id,
        "low_confidence_threshold": round(float(low_confidence_threshold), 3),
        "summary": {
            "total_sheets": len(sheets),
            "flagged_sheets": len([x for x in items if x["flags"]]),
            "reason_counts": dict(reasons_counter),
        },
        "items": items,
    }


def build_sheet_overrides_template(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    include_all: bool = False,
) -> dict[str, Any]:
    result = result or {}
    sheets = result.get("sheets_detected", [])
    if not isinstance(sheets, list):
        sheets = []

    items: list[dict[str, Any]] = []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue

        current_sheet_id = str(sheet.get("sheet_id", "")).strip()
        title = str(sheet.get("title", "")).strip()
        source_page_index = _parse_positive_int(sheet.get("source_page_index"))

        is_unmapped = current_sheet_id.startswith("UNMAPPED_")
        invalid_sheet_id = not _is_reasonable_sheet_id(current_sheet_id)
        title_missing = title in {"", "Untitled Sheet"}
        needs_override = is_unmapped or invalid_sheet_id or title_missing
        if not include_all and not needs_override:
            continue

        reason: str | None = None
        if is_unmapped:
            reason = "unmapped_sheet_id"
        elif invalid_sheet_id:
            reason = "invalid_sheet_id_format"
        elif title_missing:
            reason = "missing_sheet_title"

        items.append(
            {
                "source_page_index": source_page_index,
                "current_sheet_id": current_sheet_id,
                "sheet_id": "" if needs_override else current_sheet_id,
                "title": "" if title_missing else title,
                "reason": reason,
            }
        )

    items.sort(key=lambda row: (_sort_page_index(row.get("source_page_index")), row["current_sheet_id"]))
    return {
        "job_id": job_id,
        "summary": {
            "total_sheets": len(sheets),
            "rows_returned": len(items),
            "unmapped_count": len([x for x in items if x.get("reason") == "unmapped_sheet_id"]),
        },
        "items": items,
    }


def build_benchmark_manifest_template(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    job_input: dict[str, Any] | None,
    include_unmapped: bool = False,
    case_id: str | None = None,
) -> dict[str, Any]:
    result = result or {}
    job_input = job_input or {}

    sheets = result.get("sheets_detected", [])
    if not isinstance(sheets, list):
        sheets = []
    sorted_sheets = sorted(
        [row for row in sheets if isinstance(row, dict)],
        key=lambda row: (_sort_page_index(row.get("source_page_index")), str(row.get("sheet_id", ""))),
    )

    candidate_sheet_ids: list[str] = []
    seen_sheet_ids: set[str] = set()
    excluded_unmapped_count = 0
    for row in sorted_sheets:
        sheet_id = str(row.get("sheet_id", "")).strip()
        if not sheet_id or sheet_id in seen_sheet_ids:
            continue
        if sheet_id.startswith("UNMAPPED_"):
            excluded_unmapped_count += 1
            if not include_unmapped:
                continue
        seen_sheet_ids.add(sheet_id)
        candidate_sheet_ids.append(sheet_id)

    scale_map = _collect_scale_map(result.get("scale_analysis", {}))
    scales_by_sheet = {
        sheet_id: scale_map[sheet_id]
        for sheet_id in candidate_sheet_ids
        if sheet_id in scale_map and isinstance(scale_map[sheet_id], str) and scale_map[sheet_id].strip()
    }

    trade_scope = result.get("trade_scope", {})
    analyzed_trades = []
    if isinstance(trade_scope, dict):
        raw_trades = trade_scope.get("analyzed_trades", [])
        if isinstance(raw_trades, list):
            analyzed_trades = [str(item).strip() for item in raw_trades if str(item).strip()]

    source_total_count = _extract_total_count(result)
    quantity_sanity = {
        "require_nonempty_counts": source_total_count > 0,
        "min_total_count": source_total_count,
    }

    input_analysis_mode = str(job_input.get("analysis_mode", "auto")).strip() or "auto"
    if input_analysis_mode not in {"auto", "selected", "all"}:
        input_analysis_mode = "auto"

    input_selected_trades = job_input.get("selected_trades", [])
    normalized_selected_trades = []
    if isinstance(input_selected_trades, list):
        normalized_selected_trades = [
            str(item).strip() for item in input_selected_trades if str(item).strip()
        ]

    input_sheet_overrides = job_input.get("sheet_overrides", [])
    normalized_sheet_overrides = []
    if isinstance(input_sheet_overrides, list):
        normalized_sheet_overrides = [item for item in input_sheet_overrides if isinstance(item, dict)]

    input_notes = job_input.get("notes")
    normalized_notes = str(input_notes).strip() if isinstance(input_notes, str) else ""

    input_uploaded_files = job_input.get("uploaded_files", [])
    pdf_paths: list[str] = []
    if isinstance(input_uploaded_files, list):
        seen_paths: set[str] = set()
        for row in input_uploaded_files:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path", "")).strip()
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            pdf_paths.append(path)

    defaults: dict[str, Any] = {
        "analysis_mode": input_analysis_mode,
        "selected_trades": normalized_selected_trades,
    }
    if normalized_sheet_overrides:
        defaults["sheet_overrides"] = normalized_sheet_overrides
    if normalized_notes:
        defaults["notes"] = normalized_notes

    manifest = {
        "defaults": defaults,
        "cases": [
            {
                "case_id": case_id or f"job-{job_id[:8]}",
                "pdf_paths": pdf_paths,
                "expected": {
                    "sheet_ids": candidate_sheet_ids,
                    "scales_by_sheet": scales_by_sheet,
                    "analyzed_trades": analyzed_trades,
                    "quantity_sanity": quantity_sanity,
                },
            }
        ],
    }

    review_queue = build_review_queue(
        job_id=job_id,
        result=result,
        low_confidence_threshold=0.75,
        include_only_flagged=True,
    )

    return {
        "job_id": job_id,
        "summary": {
            "total_sheets": len(sorted_sheets),
            "candidate_sheet_ids": len(candidate_sheet_ids),
            "excluded_unmapped_count": excluded_unmapped_count,
            "sheets_with_detected_scale": len(scales_by_sheet),
            "suggested_trades": len(analyzed_trades),
            "source_total_count": source_total_count,
            "flagged_sheet_count": review_queue.get("summary", {}).get("flagged_sheets", 0),
        },
        "manifest": manifest,
    }


def _count_unknown_symbols_by_sheet(unknown_symbols: object) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    if not isinstance(unknown_symbols, list):
        return counts
    for row in unknown_symbols:
        if not isinstance(row, dict):
            continue
        sheet_id = str(row.get("sheet_id", "")).strip()
        if sheet_id:
            counts[sheet_id] += 1
    return counts


def _sheet_scale_status(scale_analysis: object) -> dict[str, dict[str, bool]]:
    status: dict[str, dict[str, bool]] = defaultdict(lambda: {"has_scale": False, "only_nts": True})
    if not isinstance(scale_analysis, dict):
        return status
    entries = scale_analysis.get("by_sheet", [])
    if not isinstance(entries, list):
        return status
    for row in entries:
        if not isinstance(row, dict):
            continue
        sheet_id = str(row.get("sheet_id", "")).strip()
        if not sheet_id:
            continue
        detected_scale = row.get("detected_scale")
        if isinstance(detected_scale, str) and detected_scale.strip():
            status[sheet_id]["has_scale"] = True
            if detected_scale.strip().upper() != "NTS":
                status[sheet_id]["only_nts"] = False
    return status


def _collect_scale_map(scale_analysis: object) -> dict[str, str]:
    if not isinstance(scale_analysis, dict):
        return {}
    entries = scale_analysis.get("by_sheet", [])
    if not isinstance(entries, list):
        return {}

    best_by_sheet: dict[str, dict[str, Any]] = {}
    for row in entries:
        if not isinstance(row, dict):
            continue
        sheet_id = str(row.get("sheet_id", "")).strip()
        if not sheet_id:
            continue
        raw_scale = row.get("detected_scale")
        if raw_scale is None:
            continue
        detected_scale = str(raw_scale).strip()
        if not detected_scale:
            continue
        confidence = _to_float(row.get("confidence"), default=0.0)
        current = best_by_sheet.get(sheet_id)
        if current is None or confidence > _to_float(current.get("confidence"), default=0.0):
            best_by_sheet[sheet_id] = {"scale": detected_scale, "confidence": confidence}
    return {sheet_id: str(row.get("scale", "")) for sheet_id, row in best_by_sheet.items()}


def _is_reasonable_sheet_id(sheet_id: str) -> bool:
    token = sheet_id.strip()
    if not token:
        return False
    if not SHEET_ID_RE.match(token):
        return False
    if " " in token:
        return False
    return True


def _reason(*, code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _item_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    ranks = [severity_rank.get(flag.get("severity", "low"), 3) for flag in item.get("flags", [])]
    best_rank = min(ranks) if ranks else 3
    confidence = float(item.get("confidence", 0.0) or 0.0)
    sheet_id = str(item.get("sheet_id", ""))
    return (best_rank, confidence, sheet_id)


def _parse_positive_int(value: object) -> int | None:
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str):
        token = value.strip()
        if token.isdigit():
            parsed = int(token)
            return parsed if parsed >= 1 else None
    return None


def _sort_page_index(value: object) -> int:
    parsed = _parse_positive_int(value)
    if parsed is None:
        return 10**9
    return parsed


def _to_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _extract_total_count(result: dict[str, Any]) -> int:
    quantity_takeoff = result.get("quantity_takeoff", {})
    if not isinstance(quantity_takeoff, dict):
        return 0
    counts = quantity_takeoff.get("counts", {})
    if not isinstance(counts, dict):
        return 0
    total = 0
    for value in counts.values():
        if isinstance(value, bool):
            total += int(value)
        elif isinstance(value, int):
            total += value
        elif isinstance(value, float):
            total += int(value)
        elif isinstance(value, str):
            token = value.strip()
            if token.isdigit():
                total += int(token)
    return total
