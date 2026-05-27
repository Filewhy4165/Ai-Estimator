from __future__ import annotations

import json
import re
from pathlib import Path

from ai_estimator.constants import TRADE_NAMES
from ai_estimator.extractors.cost_mapping import map_costs
from ai_estimator.extractors.geometry import extract_geometry
from ai_estimator.extractors.legend_symbols import extract_legend_and_symbols
from ai_estimator.extractors.model3d import build_simplified_model
from ai_estimator.extractors.pdf_loader import load_pdf_pages
from ai_estimator.extractors.scale_analyzer import analyze_scales
from ai_estimator.extractors.semantic_graph import build_semantic_graph
from ai_estimator.extractors.sheet_classifier import classify_sheets
from ai_estimator.extractors.takeoff import compute_quantity_takeoff
from ai_estimator.sheet_overrides import normalize_sheet_overrides_items
from ai_estimator.trade_scope import resolve_trade_scope
from ai_estimator.utils.json_validation import validate_output


FACILITY_SHORT_INFERRED_ID_RE = re.compile(r"^FAC-\d{4}-[A-Z]{1,2}\d{1,2}$")


def run_pipeline(
    pdf_paths: list[str],
    analysis_mode: str = "auto",
    selected_trades: list[str] | None = None,
    sheet_overrides: list[dict[str, object]] | None = None,
    notes: str | None = None,
    validate_schema: bool = True,
    schema_path: str | None = None,
) -> dict[str, object]:
    issues: list[object] = []
    selected_trades = selected_trades or []

    pages = []
    for pdf_path in pdf_paths:
        loaded_pages, load_issues = load_pdf_pages(pdf_path)
        pages.extend(loaded_pages)
        issues.extend(load_issues)

    sheets = classify_sheets(pages=pages, sheet_overrides=sheet_overrides)
    sheets_for_output = _collapse_sheets_for_output(sheets)
    issues.extend(_collect_sheet_id_inference_issues(sheets_for_output))
    trade_scope = resolve_trade_scope(
        sheets=sheets, requested_mode=analysis_mode, requested_trades=selected_trades
    )
    analyzed_trades = set(trade_scope.analyzed_trades)

    if analysis_mode == "selected" and not analyzed_trades:
        issues.append("No valid selected trades were provided.")
    if notes:
        issues.append(f"User note received: {notes[:250]}")

    scale_analysis, scale_issues = analyze_scales(pages, sheets)
    issues.extend(scale_issues)

    legend_symbols, legend_issues = extract_legend_and_symbols(pages, sheets)
    issues.extend(legend_issues)

    geometry, geometry_issues = extract_geometry(pages, sheets)
    issues.extend(geometry_issues)
    geometry = _filter_geometry_by_trade(geometry, analyzed_trades, analysis_mode)

    semantic_graph = build_semantic_graph(geometry)
    semantic_graph = _filter_semantic_graph_by_trade(semantic_graph, analyzed_trades, analysis_mode)

    model = build_simplified_model(geometry)
    quantity_takeoff, takeoff_issues = compute_quantity_takeoff(geometry)
    issues.extend(takeoff_issues)
    cost_mapping = map_costs(quantity_takeoff)

    payload: dict[str, object] = {
        "sheets_detected": [
            {
                "sheet_id": sheet.sheet_id,
                "title": sheet.title,
                "sheet_type": sheet.sheet_type,
                "discipline": sheet.trade,
                "confidence": sheet.confidence,
                "source_page_index": sheet.source_page_index + 1,
            }
            for sheet in sheets_for_output
        ],
        "trade_scope": {
            "requested_mode": trade_scope.requested_mode,
            "requested_trades": trade_scope.requested_trades,
            "detected_trades": trade_scope.detected_trades,
            "analyzed_trades": trade_scope.analyzed_trades,
            "skipped_trades": trade_scope.skipped_trades,
            "sheet_trade_map": trade_scope.sheet_trade_map,
        },
        "scale_analysis": scale_analysis,
        "legend_and_symbols": legend_symbols,
        "geometry": geometry,
        "semantic_graph": semantic_graph,
        "3d_model": model,
        "quantity_takeoff": quantity_takeoff,
        "cost_mapping": cost_mapping,
        "issues_or_ambiguities": _normalize_issues(issues),
    }

    if validate_schema:
        resolved_schema_path = schema_path or str(
            Path(__file__).parent.joinpath("schema", "output_schema.json")
        )
        is_valid, validation_errors = validate_output(payload, resolved_schema_path)
        if not is_valid:
            payload["issues_or_ambiguities"].append(
                {
                    "message": "Output failed schema validation.",
                    "severity": "error",
                    "missing_information": validation_errors[:50],
                }
            )

    return payload


def load_sheet_overrides(path: str | None) -> list[dict[str, object]] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    return normalize_sheet_overrides_items(loaded, source_name="sheet_overrides")


def load_notes(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def _filter_geometry_by_trade(
    geometry: dict[str, object], analyzed_trades: set[str], analysis_mode: str
) -> dict[str, object]:
    if analysis_mode == "all":
        return geometry
    if analysis_mode == "selected" and not analyzed_trades:
        return geometry
    if analysis_mode == "auto" and not analyzed_trades:
        return geometry

    filtered = dict(geometry)
    for bucket in ("walls", "doors", "windows", "slabs", "roofs", "fixtures", "equipment"):
        raw = geometry.get(bucket, [])
        if not isinstance(raw, list):
            filtered[bucket] = []
            continue
        filtered[bucket] = [
            item
            for item in raw
            if isinstance(item, dict) and str(item.get("trade", "other")) in analyzed_trades
        ]
    return filtered


def _filter_semantic_graph_by_trade(
    semantic_graph: dict[str, object], analyzed_trades: set[str], analysis_mode: str
) -> dict[str, object]:
    if analysis_mode == "all":
        return semantic_graph
    if analysis_mode in {"auto", "selected"} and not analyzed_trades:
        return semantic_graph

    elements = semantic_graph.get("elements", [])
    if not isinstance(elements, list):
        return semantic_graph
    kept = [
        el for el in elements if isinstance(el, dict) and str(el.get("trade", "other")) in analyzed_trades
    ]
    kept_ids = {str(el.get("id")) for el in kept if isinstance(el, dict)}

    relationships = semantic_graph.get("relationships", [])
    if not isinstance(relationships, list):
        relationships = []
    kept_relationships = [
        rel
        for rel in relationships
        if isinstance(rel, dict)
        and str(rel.get("from", "")) in kept_ids
        and str(rel.get("to", "")) in kept_ids
    ]
    return {"elements": kept, "relationships": kept_relationships}


def _normalize_issues(raw_issues: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for raw in raw_issues:
        issue = _normalize_single_issue(raw)
        if issue is None:
            continue
        key = (
            str(issue["message"]),
            str(issue["severity"]),
            tuple(issue.get("source_sheets", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(issue)
    return normalized


def _normalize_single_issue(raw: object) -> dict[str, object] | None:
    if isinstance(raw, str):
        cleaned = " ".join(raw.split())
        if not cleaned:
            return None
        return {"message": cleaned, "severity": "warning"}

    if not isinstance(raw, dict):
        cleaned = " ".join(str(raw).split())
        if not cleaned:
            return None
        return {"message": cleaned, "severity": "warning"}

    message = " ".join(str(raw.get("message", "")).split())
    if not message:
        return None
    severity = str(raw.get("severity", "warning")).lower()
    if severity not in {"info", "warning", "error"}:
        severity = "warning"

    normalized: dict[str, object] = {"message": message, "severity": severity}
    source_sheets = raw.get("source_sheets")
    if isinstance(source_sheets, list):
        cleaned_sheets = [
            " ".join(str(item).split())
            for item in source_sheets
            if " ".join(str(item).split())
        ]
        if cleaned_sheets:
            normalized["source_sheets"] = sorted(set(cleaned_sheets))
    return normalized


def sanitize_selected_trades(selected_trades_csv: str | None) -> list[str]:
    if not selected_trades_csv:
        return []
    candidates = [item.strip() for item in selected_trades_csv.split(",") if item.strip()]
    return [trade for trade in candidates if trade in TRADE_NAMES]


def _collapse_sheets_for_output(
    sheets: list,
) -> list:
    by_id: dict[str, object] = {}
    for sheet in sheets:
        existing = by_id.get(sheet.sheet_id)
        if existing is None or sheet.confidence > existing.confidence:
            by_id[sheet.sheet_id] = sheet
    return sorted(
        list(by_id.values()),
        key=lambda s: (str(s.sheet_id), int(s.source_page_index)),
    )


def _collect_sheet_id_inference_issues(sheets: list) -> list[dict[str, object]]:
    inferred_ids = sorted(
        {
            str(sheet.sheet_id)
            for sheet in sheets
            if FACILITY_SHORT_INFERRED_ID_RE.fullmatch(str(sheet.sheet_id).upper())
        }
    )
    if not inferred_ids:
        return []
    return [
        {
            "message": (
                "Some sheet IDs were inferred from building number + short sheet token. "
                "Review these IDs before final estimate handoff."
            ),
            "severity": "warning",
            "source_sheets": inferred_ids,
        }
    ]
