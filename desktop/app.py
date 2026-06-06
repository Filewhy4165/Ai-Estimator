from __future__ import annotations

import csv
from datetime import datetime
import math
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, TypeVar
from threading import Thread
from tkinter import END, BooleanVar, Button, Canvas, DoubleVar, Frame, Label, Menu, PhotoImage, StringVar, Text, Tk, Toplevel, filedialog, ttk
from urllib.parse import urlencode, urlparse
import time
import webbrowser

import requests

from ai_estimator.benchmark import run_benchmark_manifest
from ai_estimator.benchmark_compare import (
    build_benchmark_dashboard,
    build_benchmark_history,
    build_benchmark_score_timeline,
    build_latest_benchmark_trend_summary,
    evaluate_latest_benchmark_quality_gate,
    compare_latest_benchmark_reports,
    compare_reports_from_paths,
)
from ai_estimator.sheet_overrides import parse_sheet_overrides_json
from desktop.output_presenter import JsonRenderResult, render_json_preview, summarize_payload
from desktop.runtime_logging import DesktopRuntimeLogger

_TERMINAL_JOB_STATUSES = {"completed", "failed", "canceled"}
_REVIEWED_LINE_ITEMS_ALL_FILTER = "All work types"
_REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER = "All measured items"
_REVIEWED_LINE_ITEM_CSV_FIELDS = [
    "trade",
    "quantity_name",
    "quantity",
    "unit",
    "description",
    "assembly",
    "cost_code",
    "sheet_id",
    "source_page_index",
    "source_id",
    "label",
]
_REVIEWED_LINE_ITEM_ROLLUP_CSV_FIELDS = [
    "trade",
    "quantity_name",
    "quantity",
    "unit",
    "line_count",
    "cost_code",
    "source_sheets",
]
_THEME = {
    "app_bg": "#05070D",
    "surface": "#10151D",
    "surface_2": "#151C26",
    "surface_3": "#1D2633",
    "field": "#071018",
    "field_focus": "#0B1D28",
    "text": "#F8FAFC",
    "muted": "#9FB3C8",
    "line": "#253244",
    "cyan": "#19E6FF",
    "cyan_dim": "#0D7E91",
    "amber": "#FFB000",
    "orange": "#FF5A1F",
    "lime": "#95FF3D",
    "magenta": "#FF3DD7",
    "danger": "#FF3B4F",
}
_BASE_THEME = dict(_THEME)
_DEFAULT_THEME_PRESET = "clearpath_teal"
_LEGACY_DEFAULT_THEME_PRESETS = {"construction_orange"}
_THEME_PRESETS: dict[str, dict[str, str]] = {
    "construction_orange": {
        "cyan": "#19E6FF",
        "cyan_dim": "#0D7E91",
        "amber": "#FFB000",
        "orange": "#FF5A1F",
        "lime": "#95FF3D",
        "magenta": "#FF3DD7",
    },
    "electric_blue": {
        "cyan": "#3DA5FF",
        "cyan_dim": "#1E4E80",
        "amber": "#FFC857",
        "orange": "#FF7A33",
        "lime": "#8DFFB3",
        "magenta": "#A855F7",
    },
    "lime_steel": {
        "cyan": "#7CF4D9",
        "cyan_dim": "#2A6F63",
        "amber": "#EAC435",
        "orange": "#F08A24",
        "lime": "#B5FF5E",
        "magenta": "#F973C1",
    },
    "clearpath_teal": {
        "cyan": "#38E8FF",
        "cyan_dim": "#1B7986",
        "amber": "#FFC857",
        "orange": "#FF8A3D",
        "lime": "#A8FF5A",
        "magenta": "#FF6B8A",
        "danger": "#FF4F61",
    },
}
_THEME_PRESET_OPTIONS = tuple(_THEME_PRESETS.keys())
_THEME_SURFACE_OVERRIDES: dict[str, dict[str, dict[str, str]]] = {
    "clearpath_teal": {
        "dark": {
            "app_bg": "#071012",
            "surface": "#0F1D21",
            "surface_2": "#13252A",
            "surface_3": "#183038",
            "field": "#071012",
            "field_focus": "#0A1518",
            "text": "#EFFDFA",
            "muted": "#8DA6A5",
            "line": "#274247",
        },
        "light": {
            "app_bg": "#EDF8F6",
            "surface": "#F7FFFD",
            "surface_2": "#E4F5F2",
            "surface_3": "#D2EAE6",
            "field": "#FFFFFF",
            "field_focus": "#EAFBFA",
            "text": "#061214",
            "muted": "#416161",
            "line": "#B1CFCC",
        },
    },
}
_DARK_SURFACES = {
    "app_bg": "#05070D",
    "surface": "#10151D",
    "surface_2": "#151C26",
    "surface_3": "#1D2633",
    "field": "#071018",
    "field_focus": "#0B1D28",
    "text": "#F8FAFC",
    "muted": "#9FB3C8",
    "line": "#253244",
}
_LIGHT_SURFACES = {
    "app_bg": "#F1F5FB",
    "surface": "#FFFFFF",
    "surface_2": "#E8EEF7",
    "surface_3": "#DDE7F4",
    "field": "#FFFFFF",
    "field_focus": "#EEF7FF",
    "text": "#0B1324",
    "muted": "#334155",
    "line": "#9FB2CC",
}


def resolve_theme_preset(preset: str, *, migrate_legacy_default: bool = False) -> str:
    normalized_preset = preset.strip() or _DEFAULT_THEME_PRESET
    if migrate_legacy_default and normalized_preset in _LEGACY_DEFAULT_THEME_PRESETS:
        return _DEFAULT_THEME_PRESET
    if normalized_preset not in _THEME_PRESETS:
        return _DEFAULT_THEME_PRESET
    return normalized_preset


def resolve_theme_palette(preset: str, dark_mode: bool) -> dict[str, str]:
    normalized_preset = resolve_theme_preset(preset)

    surfaces = _DARK_SURFACES if dark_mode else _LIGHT_SURFACES
    mode_key = "dark" if dark_mode else "light"
    surface_overrides = _THEME_SURFACE_OVERRIDES.get(normalized_preset, {}).get(mode_key, {})
    return {
        **_BASE_THEME,
        **surfaces,
        **surface_overrides,
        **_THEME_PRESETS[normalized_preset],
    }
_OUTPUT_JSON_PREVIEW_MAX_CHARS = 240_000
_OUTPUT_JSON_FULL_RENDER_MAX_CHARS = 1_500_000
_OUTPUT_LOG_MAX_CHARS = 180_000
_OUTPUT_TRIM_NOTICE = "[Output trimmed to keep the latest activity visible.]"
_BACKGROUND_BUSY_MESSAGE = "Another request is already running. Wait for it to finish."
_BGTaskT = TypeVar("_BGTaskT")


def parse_selected_trade_tokens(selected_trades_csv: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for raw in selected_trades_csv.split(","):
        token = raw.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def validate_selected_trade_scope(
    *,
    analysis_mode: str,
    selected_trades_csv: str,
    valid_trades: list[str] | None,
) -> list[str]:
    mode = analysis_mode.strip()
    if mode not in {"auto", "selected", "all"}:
        raise ValueError("analysis_mode must be auto, selected, or all.")

    selected_tokens = parse_selected_trade_tokens(selected_trades_csv)
    if mode == "selected" and not selected_tokens:
        raise ValueError("Selected mode requires at least one trade token.")

    if valid_trades:
        allowed = set(valid_trades)
        unknown = [token for token in selected_tokens if token not in allowed]
        if unknown:
            raise ValueError(f"Unknown trade(s): {', '.join(unknown)}.")

    return selected_tokens


def format_reviewed_takeoff_lines_payload(
    payload: dict[str, Any],
    *,
    current_job_id: str = "",
) -> str:
    job_id = str(payload.get("job_id", "")).strip() or current_job_id.strip()
    items = payload.get("line_items", [])
    summary = payload.get("summary", {})
    lines = [
        "Reviewed Takeoff Lines",
        f"Job: {job_id or 'unknown'}",
        f"Items: {payload.get('item_count', 0)}",
    ]
    if isinstance(summary, dict):
        total_by_unit = summary.get("total_by_unit", {})
        if isinstance(total_by_unit, dict) and total_by_unit:
            totals = ", ".join(
                f"{value} {unit}" for unit, value in sorted(total_by_unit.items())
            )
            lines.append(f"Total: {totals}")
    lines.append("")

    if not isinstance(items, list) or not items:
        lines.extend(
            [
                "No reviewed takeoff line items found yet.",
                "",
                "To create these:",
                "1. Open a completed job.",
                "2. Select a sheet in Sheet Navigator.",
                "3. Click Measure Scale Visually.",
                "4. Draw a measurement, check Include this measurement in the takeoff, choose work type/item, and save.",
            ]
        )
        return "\n".join(lines)

    for index, raw_item in enumerate(items[:500], start=1):
        if not isinstance(raw_item, dict):
            continue
        trade = str(raw_item.get("trade", "")).strip() or "unknown work type"
        name = str(raw_item.get("quantity_name", "")).strip() or "line item"
        quantity = raw_item.get("quantity", "")
        unit = str(raw_item.get("unit", "")).strip()
        description = str(raw_item.get("description", "")).strip()
        cost_code = str(raw_item.get("cost_code", "")).strip()
        sheet = str(raw_item.get("sheet_id", "")).strip()
        page = str(raw_item.get("source_page_index", "") or "").strip()
        source = f"{sheet}" if sheet else "sheet unknown"
        if page:
            source += f" page {page}"
        detail_parts = [f"{index}. {trade} - {name}: {quantity} {unit}".strip()]
        if description:
            detail_parts.append(f"description: {description}")
        if cost_code:
            detail_parts.append(f"cost code: {cost_code}")
        detail_parts.append(f"source: {source}")
        lines.append(" | ".join(detail_parts))

    if isinstance(items, list) and len(items) > 500:
        lines.append(f"... {len(items) - 500} more line item(s) not shown.")
    return "\n".join(lines)


def format_api_health_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        return "API Health\nStatus: unknown\n\nThe server did not return a JSON object."

    status = str(payload.get("status", "unknown")).strip() or "unknown"
    app_version = str(payload.get("app_version", "")).strip()
    process_id = str(payload.get("process_id", "")).strip()
    started_at = str(payload.get("started_at", "")).strip()
    db_path = str(payload.get("db_path", "")).strip()

    lines = [
        "API Health",
        f"Status: {status}",
        f"Version: {app_version or 'not reported'}",
        f"Process ID: {process_id or 'not reported'}",
        f"Started: {started_at or 'not reported'}",
        f"Database: {db_path or 'not reported'}",
    ]
    if status != "ok":
        lines.append("")
        lines.append("Warning: API status is not ok.")
    if not app_version or not process_id or not started_at:
        lines.append("")
        lines.append(
            "Note: This server did not report full build metadata. If the app was just updated, restart the local server."
        )
    return "\n".join(lines)


def reviewed_takeoff_line_item_values(raw_item: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    trade = str(raw_item.get("trade", "")).strip() or "unknown work type"
    quantity_name = str(raw_item.get("quantity_name", "")).strip() or "line item"
    quantity = raw_item.get("quantity", "")
    if isinstance(quantity, (int, float)):
        quantity_text = f"{quantity:g}"
    else:
        quantity_text = str(quantity).strip() or "-"
    unit = str(raw_item.get("unit", "")).strip() or "-"
    description = str(raw_item.get("description", "")).strip() or "-"
    cost_code = str(raw_item.get("cost_code", "")).strip() or "-"
    sheet = str(raw_item.get("sheet_id", "")).strip()
    page = str(raw_item.get("source_page_index", "") or "").strip()
    source = sheet or "sheet unknown"
    if page:
        source = f"{source} page {page}"
    return trade, quantity_name, quantity_text, unit, description, cost_code, source


def reviewed_takeoff_line_item_source(raw_item: dict[str, Any]) -> tuple[str, int | None, str]:
    sheet_id = str(raw_item.get("sheet_id", "")).strip()
    raw_page = raw_item.get("source_page_index")
    page_index: int | None = None
    if isinstance(raw_page, int) and raw_page > 0:
        page_index = raw_page
    elif isinstance(raw_page, str) and raw_page.strip().isdigit():
        parsed_page = int(raw_page.strip())
        if parsed_page > 0:
            page_index = parsed_page
    source_id = str(raw_item.get("source_id", "")).strip()
    return sheet_id, page_index, source_id


def reviewed_takeoff_trade_filter_options(items: object) -> list[str]:
    trades: set[str] = set()
    if isinstance(items, list):
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            trade = str(raw_item.get("trade", "")).strip()
            if trade:
                trades.add(trade)
    return [_REVIEWED_LINE_ITEMS_ALL_FILTER, *sorted(trades, key=str.casefold)]


def reviewed_takeoff_item_filter_options(items: object, selected_trade: str = "") -> list[str]:
    names: set[str] = set()
    for raw_item in filter_reviewed_takeoff_line_items(items, selected_trade):
        name = str(raw_item.get("quantity_name", "")).strip()
        if name:
            names.add(name)
    return [_REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER, *sorted(names, key=str.casefold)]


def filter_reviewed_takeoff_line_items(
    items: object,
    selected_trade: str,
    selected_item: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized_trade = selected_trade.strip()
    normalized_item = selected_item.strip()
    all_items = not normalized_item or normalized_item == _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER
    if not normalized_trade or normalized_trade == _REVIEWED_LINE_ITEMS_ALL_FILTER:
        trade_filtered = [raw_item for raw_item in items if isinstance(raw_item, dict)]
    else:
        trade_filtered = [
            raw_item
            for raw_item in items
            if isinstance(raw_item, dict)
            and str(raw_item.get("trade", "")).strip().casefold() == normalized_trade.casefold()
        ]
    if all_items:
        return trade_filtered
    return [
        raw_item
        for raw_item in trade_filtered
        if str(raw_item.get("quantity_name", "")).strip().casefold() == normalized_item.casefold()
    ]


def reviewed_takeoff_line_item_totals_by_unit(items: object) -> dict[str, float]:
    totals: dict[str, float] = {}
    if not isinstance(items, list):
        return totals
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        raw_quantity = raw_item.get("quantity")
        if isinstance(raw_quantity, (int, float)):
            quantity = float(raw_quantity)
        elif isinstance(raw_quantity, str):
            try:
                quantity = float(raw_quantity.strip())
            except ValueError:
                continue
        else:
            continue
        unit = str(raw_item.get("unit", "")).strip() or "unit"
        totals[unit] = round(totals.get(unit, 0.0) + quantity, 6)
    return totals


def format_reviewed_takeoff_line_item_totals(totals: dict[str, float]) -> str:
    if not totals:
        return "none"
    return ", ".join(
        f"{quantity:g} {unit}"
        for unit, quantity in sorted(totals.items(), key=lambda item: item[0].casefold())
    )


def reviewed_takeoff_line_item_csv_row(raw_item: dict[str, Any]) -> dict[str, str]:
    row: dict[str, str] = {}
    for field in _REVIEWED_LINE_ITEM_CSV_FIELDS:
        value = raw_item.get(field, "")
        if isinstance(value, float):
            row[field] = f"{value:g}"
        elif isinstance(value, int):
            row[field] = str(value)
        else:
            row[field] = str(value or "").strip()
    return row


def reviewed_takeoff_line_item_csv_rows(items: object) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    return [
        reviewed_takeoff_line_item_csv_row(raw_item)
        for raw_item in items
        if isinstance(raw_item, dict)
    ]


def reviewed_takeoff_line_item_rollups(items: object) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    rollups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        trade = str(raw_item.get("trade", "")).strip() or "unknown work type"
        name = str(raw_item.get("quantity_name", "")).strip() or "line item"
        unit = str(raw_item.get("unit", "")).strip() or "unit"
        cost_code = str(raw_item.get("cost_code", "")).strip() or "-"
        key = (trade, name, unit, cost_code)

        entry = rollups.setdefault(
            key,
            {
                "trade": trade,
                "quantity_name": name,
                "unit": unit,
                "cost_code": cost_code,
                "quantity": 0.0,
                "line_count": 0,
                "source_sheets": set(),
            },
        )
        entry["line_count"] += 1

        raw_quantity = raw_item.get("quantity")
        if isinstance(raw_quantity, (int, float)):
            entry["quantity"] += float(raw_quantity)
        elif isinstance(raw_quantity, str):
            try:
                entry["quantity"] += float(raw_quantity.strip())
            except ValueError:
                pass

        sheet = str(raw_item.get("sheet_id", "")).strip()
        if sheet:
            entry["source_sheets"].add(sheet)

    rows: list[dict[str, Any]] = []
    for entry in rollups.values():
        source_sheets = entry.get("source_sheets", set())
        source_display = ", ".join(sorted(source_sheets, key=str.casefold)) if isinstance(source_sheets, set) else ""
        rows.append(
            {
                **entry,
                "quantity": round(float(entry.get("quantity", 0.0)), 6),
                "source_sheets": source_display or "-",
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            str(row.get("trade", "")).casefold(),
            str(row.get("quantity_name", "")).casefold(),
            str(row.get("unit", "")).casefold(),
            str(row.get("cost_code", "")).casefold(),
        ),
    )


def reviewed_takeoff_line_item_rollup_values(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    quantity = row.get("quantity", 0)
    if isinstance(quantity, (int, float)):
        quantity_text = f"{quantity:g}"
    else:
        quantity_text = str(quantity).strip() or "0"
    return (
        str(row.get("trade", "")).strip() or "unknown work type",
        str(row.get("quantity_name", "")).strip() or "line item",
        quantity_text,
        str(row.get("unit", "")).strip() or "unit",
        str(row.get("line_count", "")).strip() or "0",
        str(row.get("cost_code", "")).strip() or "-",
        str(row.get("source_sheets", "")).strip() or "-",
    )


def reviewed_takeoff_line_item_rollup_filter_values(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("trade", "")).strip() or "unknown work type",
        str(row.get("quantity_name", "")).strip() or "line item",
    )


def reviewed_takeoff_line_item_rollup_match_values(row: dict[str, Any]) -> tuple[str, str, str, str]:
    trade, quantity_name = reviewed_takeoff_line_item_rollup_filter_values(row)
    return (
        trade,
        quantity_name,
        str(row.get("unit", "")).strip() or "unit",
        str(row.get("cost_code", "")).strip() or "-",
    )


def reviewed_takeoff_line_item_matches_rollup(raw_item: object, row: dict[str, Any]) -> bool:
    if not isinstance(raw_item, dict):
        return False
    raw_values = (
        str(raw_item.get("trade", "")).strip() or "unknown work type",
        str(raw_item.get("quantity_name", "")).strip() or "line item",
        str(raw_item.get("unit", "")).strip() or "unit",
        str(raw_item.get("cost_code", "")).strip() or "-",
    )
    return raw_values == reviewed_takeoff_line_item_rollup_match_values(row)


def reviewed_takeoff_line_item_rollup_csv_row(row: dict[str, Any]) -> dict[str, str]:
    values = reviewed_takeoff_line_item_rollup_values(row)
    return dict(zip(_REVIEWED_LINE_ITEM_ROLLUP_CSV_FIELDS, values))


def reviewed_takeoff_line_item_rollup_csv_rows(items: object) -> list[dict[str, str]]:
    return [
        reviewed_takeoff_line_item_rollup_csv_row(row)
        for row in reviewed_takeoff_line_item_rollups(items)
    ]


class HoverTooltip:
    def __init__(
        self,
        widget: object,
        text: str,
        *,
        delay_ms: int = 450,
        wrap_length: int = 360,
    ) -> None:
        self.widget = widget
        self.text = text.strip()
        self.delay_ms = delay_ms
        self.wrap_length = wrap_length
        self._after_id: str | None = None
        self._tip_window: Toplevel | None = None

        bind = getattr(widget, "bind", None)
        if callable(bind):
            bind("<Enter>", self._on_enter, add="+")
            bind("<Leave>", self._on_leave, add="+")
            bind("<ButtonPress>", self._on_leave, add="+")

    def set_text(self, text: str) -> None:
        self.text = text.strip()
        self._hide()

    def _on_enter(self, _event: object = None) -> None:
        self._schedule_show()

    def _on_leave(self, _event: object = None) -> None:
        self._cancel_show()
        self._hide()

    def _schedule_show(self) -> None:
        if not self.text:
            return
        after = getattr(self.widget, "after", None)
        if not callable(after):
            return
        self._cancel_show()
        self._after_id = after(self.delay_ms, self._show)

    def _cancel_show(self) -> None:
        if not self._after_id:
            return
        after_cancel = getattr(self.widget, "after_cancel", None)
        if callable(after_cancel):
            try:
                after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._tip_window is not None or not self.text:
            return
        try:
            pointer_x = int(getattr(self.widget, "winfo_pointerx")())
            pointer_y = int(getattr(self.widget, "winfo_pointery")())
        except Exception:
            return

        tip = Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.wm_attributes("-topmost", True)
        except Exception:
            pass
        tip.geometry(f"+{pointer_x + 14}+{pointer_y + 16}")

        label = Label(
            tip,
            text=self.text,
            justify="left",
            wraplength=self.wrap_length,
            background=_THEME["surface_2"],
            foreground=_THEME["text"],
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        label.pack()
        self._tip_window = tip

    def _hide(self) -> None:
        if self._tip_window is None:
            return
        try:
            self._tip_window.destroy()
        except Exception:
            pass
        self._tip_window = None


class DesktopEstimatorApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("EstimateForge Command Center")
        self.root.geometry("1440x900")
        self.root.minsize(1200, 740)
        self.settings_path = Path.home() / ".ai_estimator_desktop_settings.json"
        self.projects_store_path = Path.home() / ".ai_estimator_projects.json"

        self.api_url = StringVar(value="http://127.0.0.1:8000")
        self.api_key = StringVar(value=os.environ.get("AI_ESTIMATOR_API_KEY", ""))
        self.tenant_id = StringVar(value=os.environ.get("AI_ESTIMATOR_TENANT_ID", "default"))
        self.analysis_mode = StringVar(value="auto")
        self.selected_trades = StringVar(value="")
        self.sheet_overrides_path = StringVar(value="")
        self.spec_profile_ids = StringVar(value="")
        self.spec_organization = StringVar(value="NASA")
        self.include_public_specs = BooleanVar(value=True)
        self.publish_uploaded_specs = BooleanVar(value=False)
        self.current_job_id = StringVar(value="")
        self.visual_review_sheet_id = StringVar(value="")
        self.visual_review_page_index = StringVar(value="")
        self.scale_measured_pdf_units = StringVar(value="")
        self.scale_known_length_ft = StringVar(value="")
        self.notes = StringVar(value="")
        self.include_all_template = BooleanVar(value=False)
        self.include_unmapped_benchmark = BooleanVar(value=True)
        self.beginner_mode = BooleanVar(value=True)
        self.show_advanced_tools = BooleanVar(value=False)
        self.auto_poll_enabled = BooleanVar(value=False)
        self.prune_statuses = StringVar(value="completed,failed,canceled")
        self.prune_older_than_hours = StringVar(value="168")
        self.prune_limit = StringVar(value="200")
        self.prune_cleanup_uploads = BooleanVar(value=False)
        self.active_project_name = StringVar(value="")
        self.project_setup_name = StringVar(value="")
        self.guided_step = StringVar(value="trade")
        self.guided_trade_strategy = StringVar(value="all")
        self.guided_run_objective = StringVar(value="takeoff_and_estimation")
        self.guided_step_title = StringVar(value="Step 1: Trade Selection Settings")
        self.guided_step_detail = StringVar(
            value="Choose how trades are selected, then click Guided Proceed."
        )
        self.pipe_length_feet = StringVar(value="10")
        self.pipe_length_inches = StringVar(value="0")
        self.pipe_run_count = StringVar(value="1")
        self.pipe_waste_percent = StringVar(value="10")
        self.pipe_calc_result = StringVar(value="Pipe calculator ready.")
        self.concrete_length_feet = StringVar(value="20")
        self.concrete_width_feet = StringVar(value="12")
        self.concrete_depth_inches = StringVar(value="4")
        self.concrete_waste_percent = StringVar(value="8")
        self.concrete_calc_result = StringVar(value="Concrete/gravel calculator ready.")
        self.carpentry_wall_length_feet = StringVar(value="16")
        self.carpentry_wall_height_feet = StringVar(value="8")
        self.carpentry_stud_spacing_inches = StringVar(value="16")
        self.carpentry_waste_percent = StringVar(value="10")
        self.carpentry_calc_result = StringVar(value="Carpentry framing calculator ready.")
        self.hvac_diameter_inches = StringVar(value="12")
        self.hvac_run_length_feet = StringVar(value="20")
        self.hvac_run_count = StringVar(value="4")
        self.hvac_waste_percent = StringVar(value="10")
        self.hvac_calc_result = StringVar(value="Sheet metal / HVAC calculator ready.")
        self.heavy_area_sqft = StringVar(value="1000")
        self.heavy_depth_inches = StringVar(value="6")
        self.heavy_swell_percent = StringVar(value="15")
        self.heavy_calc_result = StringVar(value="Heavy earthwork calculator ready.")
        self.theme_preset = StringVar(value=_DEFAULT_THEME_PRESET)
        self.dark_mode_enabled = BooleanVar(value=True)
        self.banner_animation_enabled = BooleanVar(value=True)
        self.auto_poll_interval_ms = 2000
        self.auto_poll_handle: str | None = None
        self.benchmark_task_running = False
        self.end_to_end_task_running = False
        self.request_task_running = False
        self.job_polling = False
        self.file_scan_running = False
        self.trade_discovery_running = False
        self._api_bootstrap_in_progress = False
        self._local_api_process: subprocess.Popen[object] | None = None
        self.request_progress_text = StringVar(value="")
        self.run_phase_text = StringVar(value="")
        self.run_progress_value = DoubleVar(value=0.0)
        self.job_progress_message = ""
        self._progress_bar_running = False
        self._auto_poll_cycle = 0
        self.status_text = StringVar(value="Ready.")
        self.json_view_status_text = StringVar(value="JSON preview mode.")
        self.header_mode_text = StringVar(value="Mode: auto")
        self.header_job_text = StringVar(value="Job: none")
        self.header_files_text = StringVar(value="Files: none")
        self.summary_banner_text = StringVar(value="Estimator summary will appear after a completed run.")
        self.reviewed_line_items_banner_text = StringVar(
            value="Reviewed takeoff line items will appear after visual measurement saves."
        )
        self.reviewed_rollup_banner_text = StringVar(
            value="Grouped reviewed takeoff totals will appear after visual measurement saves."
        )
        self.reviewed_line_items_filter_trade = StringVar(value=_REVIEWED_LINE_ITEMS_ALL_FILTER)
        self.reviewed_line_items_filter_item = StringVar(value=_REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER)
        self.sheet_banner_text = StringVar(value="Sheet navigator will appear after a completed run.")
        self.trade_selection_hint_text = StringVar(value="All work types will be analyzed.")
        self.trade_catalog: list[str] = []
        self.analysis_mode_catalog: list[str] = ["auto", "selected", "all"]
        self.files: list[str] = []
        self._file_scan_meta: dict[str, dict[str, object]] = {}
        self._file_scan_token = 0
        self._tooltips: list[HoverTooltip] = []
        self._control_help_entries: dict[str, str] = {}
        self._control_specs: dict[str, dict[str, str]] = {}
        self._control_widgets: dict[str, object] = {}
        self._field_label_widgets: dict[str, object] = {}
        self._control_tooltips: dict[str, HoverTooltip] = {}
        self._field_label_specs: dict[str, dict[str, str]] = {}
        self._field_label_tooltips: dict[str, HoverTooltip] = {}
        self._field_tooltip_specs: dict[str, dict[str, str]] = {}
        self._field_tooltips: dict[str, HoverTooltip] = {}
        self.files_list: Text | None = None
        self.files_list_y_scroll: ttk.Scrollbar | None = None
        self.actions_notebook: ttk.Notebook | None = None
        self._advanced_tab_widgets: list[tuple[ttk.Frame, str]] = []
        self.guided_flow_frame: ttk.LabelFrame | None = None
        self.guided_objective_frame: ttk.LabelFrame | None = None
        self.guided_selected_frame: ttk.LabelFrame | None = None
        self.guided_trade_options_frame: ttk.Frame | None = None
        self.guided_back_button: ttk.Button | None = None
        self.guided_proceed_button: ttk.Button | None = None
        self.guided_execute_button: ttk.Button | None = None
        self.guided_skip_button: ttk.Button | None = None
        self.guided_discover_button: ttk.Button | None = None
        self.theme_combo: ttk.Combobox | None = None
        self.construction_banner: Canvas | None = None
        self._banner_phase = 0
        self._banner_after_id: str | None = None
        self.trade_option_vars: dict[str, BooleanVar] = {}
        self.calculators_canvas: Canvas | None = None
        self._calculator_popups: dict[str, Toplevel] = {}
        self.logo_image: PhotoImage | None = None
        self.app_icon_image: PhotoImage | None = None
        self.logo_label: Label | None = None
        self.main_scroll_canvas: Canvas | None = None
        self.setup_scroll_canvas: Canvas | None = None
        self.project_selector_combo: ttk.Combobox | None = None
        self.spec_org_combo: ttk.Combobox | None = None
        self.setup_project_combo: ttk.Combobox | None = None
        self.setup_window: Toplevel | None = None
        self.scale_calibration_window: Toplevel | None = None
        self._setup_window_is_open = False
        self._inline_setup_widgets: list[object] = []
        self._native_menu: Menu | None = None
        self._native_menu_visible = True
        self._menu_hide_after_id: str | None = None
        self._menu_show_after_id: str | None = None
        self._menu_hover_zone_px = 36
        self._menu_hover_zone_top_px = 0
        self._menu_show_delay_ms = 180
        self._menu_hide_delay_ms = 1300
        self._menu_min_visible_ms = 900
        self._menu_last_activity_monotonic = 0.0
        self._menu_visible_since_monotonic = 0.0
        self.project_profiles: dict[str, dict[str, object]] = {}
        self.spec_catalog: list[dict[str, object]] = []
        self.spec_org_catalog: list[str] = []
        self._background_action_token = 0
        self._json_render_result: JsonRenderResult | None = None
        self._json_source_payload: dict[str, Any] = {}
        self._json_view_mode = "preview"
        self._settings_io_warning_active = False
        self.runtime_logger = DesktopRuntimeLogger("EstimateForge")
        self.logo_path_candidates: list[Path] = [
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "estimate_forge_small.png",
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "estimate_forge_complete_logo.png",
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "estimate_forge_e_logo.png",
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "tech_build_logo.png",
        ]
        self.icon_path_candidates: list[Path] = [
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "estimate_forge_e_logo.png",
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "estimate_forge_small.png",
        ]
        self.output_y_scroll: ttk.Scrollbar | None = None
        self.output_x_scroll: ttk.Scrollbar | None = None
        self.results_notebook: ttk.Notebook | None = None
        self.summary_result_tree: ttk.Treeview | None = None
        self.reviewed_line_items_tree: ttk.Treeview | None = None
        self.reviewed_line_items_rollup_tree: ttk.Treeview | None = None
        self.reviewed_line_items_by_tree_id: dict[str, dict[str, Any]] = {}
        self.reviewed_line_items_rollup_by_tree_id: dict[str, dict[str, Any]] = {}
        self.reviewed_line_items_all: list[dict[str, Any]] = []
        self.reviewed_line_items_active_rollup_filter: dict[str, Any] | None = None
        self.reviewed_line_items_filter_combo: ttk.Combobox | None = None
        self.reviewed_line_items_item_filter_combo: ttk.Combobox | None = None
        self.sheet_navigator_tree: ttk.Treeview | None = None
        self.latest_payload: dict[str, object] = {}
        self.last_result_payload: dict[str, object] = {}

        self.analysis_mode.trace_add("write", lambda *_: self._refresh_header_summary())
        self.analysis_mode.trace_add("write", lambda *_: self._sync_analysis_mode_to_guided())
        self.analysis_mode.trace_add("write", lambda *_: self._refresh_trade_selection_hint())
        self.current_job_id.trace_add("write", lambda *_: self._refresh_header_summary())
        self.guided_step.trace_add("write", lambda *_: self._refresh_guided_flow())
        self.guided_trade_strategy.trace_add("write", lambda *_: self._sync_guided_trade_strategy())
        self.theme_preset.trace_add("write", lambda *_: self._apply_visual_theme(update_status=True))
        self.dark_mode_enabled.trace_add("write", lambda *_: self._apply_visual_theme(update_status=True))
        self.banner_animation_enabled.trace_add("write", lambda *_: self._toggle_banner_animation())

        self._configure_style()
        self._build_ui()
        self._install_app_icon()
        self._bind_shortcuts()
        self._load_project_profiles()
        self._load_settings()
        self._enable_hover_menu_mode()
        self._refresh_files_label()
        self.root.after(700, self._start_local_api_if_needed)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _resolve_theme_palette(self) -> dict[str, str]:
        return resolve_theme_palette(
            self.theme_preset.get(),
            bool(self.dark_mode_enabled.get()),
        )

    def _apply_visual_theme(self, *, update_status: bool) -> None:
        palette = self._resolve_theme_palette()
        _THEME.update(palette)
        self._configure_style()

        if self.main_scroll_canvas is not None:
            try:
                self.main_scroll_canvas.configure(background=palette["app_bg"])
            except Exception:
                pass
        if self.setup_scroll_canvas is not None:
            try:
                self.setup_scroll_canvas.configure(background=palette["surface"])
            except Exception:
                pass

        if self.construction_banner is not None:
            try:
                self.construction_banner.configure(
                    background=palette["app_bg"],
                    highlightbackground=palette["cyan"],
                )
            except Exception:
                pass
            self._draw_construction_banner(self.construction_banner)

        if self.files_list is not None:
            try:
                self.files_list.configure(
                    background=palette["field"],
                    foreground=palette["text"],
                    insertbackground=palette["cyan"],
                    selectbackground=palette["cyan"],
                    selectforeground="#041016",
                )
            except Exception:
                pass
        if getattr(self, "output", None) is not None:
            try:
                self.output.configure(
                    background=palette["field"],
                    foreground=palette["text"],
                    insertbackground=palette["cyan"],
                    selectbackground=palette["cyan"],
                    selectforeground="#041016",
                )
            except Exception:
                pass
        self._install_company_logo()
        self._toggle_banner_animation(update_status=False)
        if update_status:
            mode_text = "dark" if bool(self.dark_mode_enabled.get()) else "light"
            self.status_text.set(
                f"Theme applied: {self.theme_preset.get().strip()} ({mode_text} mode)."
            )
            self._save_settings()

    def _install_company_logo(self) -> None:
        if self.logo_label is None:
            return
        try:
            self.logo_label.configure(background=_THEME["surface"])
        except Exception:
            pass

        for candidate in self.logo_path_candidates:
            if not candidate.exists():
                continue
            try:
                image = PhotoImage(file=str(candidate))
                max_width = 200
                max_height = 56
                down_x = max(1, math.ceil(image.width() / max_width))
                down_y = max(1, math.ceil(image.height() / max_height))
                downsample = max(down_x, down_y)
                if downsample > 1:
                    image = image.subsample(downsample, downsample)
                self.logo_image = image
                self.logo_label.configure(image=self.logo_image, text="")
                return
            except Exception:
                continue

        self.logo_image = None
        self.logo_label.configure(image="", text="EstimateForge", fg=_THEME["muted"])

    def _install_app_icon(self) -> None:
        for candidate in self.icon_path_candidates:
            if not candidate.exists():
                continue
            try:
                icon_image = PhotoImage(file=str(candidate))
                down_x = max(1, math.ceil(icon_image.width() / 128))
                down_y = max(1, math.ceil(icon_image.height() / 128))
                downsample = max(down_x, down_y)
                if downsample > 1:
                    icon_image = icon_image.subsample(downsample, downsample)
                self.app_icon_image = icon_image
                self.root.iconphoto(True, self.app_icon_image)
                return
            except Exception:
                continue

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available_themes = set(style.theme_names())
        if "clam" in available_themes:
            style.theme_use("clam")
        elif "vista" in available_themes:
            style.theme_use("vista")
        elif "xpnative" in available_themes:
            style.theme_use("xpnative")

        p = _THEME
        self.root.configure(background=p["app_bg"])
        self.root.option_add("*Menu.background", p["surface_2"])
        self.root.option_add("*Menu.foreground", p["text"])
        self.root.option_add("*Menu.activeBackground", p["cyan"])
        self.root.option_add("*Menu.activeForeground", "#041016")
        self.root.option_add("*TCombobox*Listbox.background", p["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["cyan"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#041016")

        style.configure("App.TFrame", background=p["app_bg"])
        style.configure("Hero.TFrame", background=p["app_bg"])
        style.configure("TFrame", background=p["surface"])
        style.configure(
            "Panel.TFrame",
            background=p["surface"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Status.TFrame",
            background=p["surface_2"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "TLabelframe",
            background=p["surface"],
            bordercolor=p["line"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=p["surface"],
            foreground=p["cyan"],
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "TButton",
            padding=(12, 8),
            font=("Segoe UI Semibold", 9),
            background=p["surface_3"],
            foreground=p["text"],
            bordercolor=p["line"],
            lightcolor=p["surface_3"],
            darkcolor=p["surface_3"],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[
                ("disabled", "#111827"),
                ("pressed", p["cyan_dim"]),
                ("active", "#203142"),
            ],
            foreground=[("disabled", "#64748B"), ("active", p["cyan"])],
            bordercolor=[("active", p["cyan"]), ("pressed", p["cyan"])],
            relief=[("pressed", "sunken"), ("!pressed", "flat")],
        )
        style.configure(
            "Primary.TButton",
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
            background=p["amber"],
            foreground="#140E00",
            bordercolor=p["orange"],
            lightcolor=p["amber"],
            darkcolor=p["amber"],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[("disabled", "#3B2D11"), ("pressed", p["orange"]), ("active", "#FFD166")],
            foreground=[("disabled", "#8B7355"), ("active", "#05070D")],
            bordercolor=[("active", p["lime"]), ("pressed", p["orange"])],
            relief=[("pressed", "sunken"), ("!pressed", "flat")],
        )
        style.configure(
            "Accent.TButton",
            padding=(12, 8),
            font=("Segoe UI Semibold", 9),
            background=p["cyan"],
            foreground="#041016",
            bordercolor=p["cyan"],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", p["cyan_dim"]), ("active", p["lime"])],
            foreground=[("active", "#041016")],
        )
        style.configure(
            "TCheckbutton",
            padding=(4, 3),
            font=("Segoe UI", 9),
            background=p["surface"],
            foreground=p["text"],
            indicatorcolor=p["field"],
        )
        style.map(
            "TCheckbutton",
            background=[("active", p["surface_2"])],
            foreground=[("active", p["cyan"]), ("disabled", "#64748B")],
        )
        style.configure(
            "TRadiobutton",
            padding=(4, 3),
            font=("Segoe UI", 9),
            background=p["surface"],
            foreground=p["text"],
            indicatorcolor=p["field"],
        )
        style.map(
            "TRadiobutton",
            background=[("active", p["surface_2"])],
            foreground=[("active", p["cyan"]), ("disabled", "#64748B")],
        )
        style.configure("TLabel", font=("Segoe UI", 9), background=p["surface"], foreground=p["text"])
        style.configure(
            "FormLabel.TLabel",
            font=("Segoe UI Semibold", 9),
            background=p["surface"],
            foreground=p["muted"],
        )
        style.configure(
            "TEntry",
            font=("Segoe UI", 9),
            fieldbackground=p["field"],
            foreground=p["text"],
            bordercolor=p["line"],
            insertcolor=p["cyan"],
            lightcolor=p["field"],
            darkcolor=p["field"],
            borderwidth=1,
        )
        style.map(
            "TEntry",
            fieldbackground=[("focus", p["field_focus"])],
            bordercolor=[("focus", p["cyan"])],
            foreground=[("disabled", "#64748B")],
        )
        style.configure(
            "TCombobox",
            font=("Segoe UI", 9),
            fieldbackground=p["field"],
            foreground=p["text"],
            background=p["surface_3"],
            arrowcolor=p["cyan"],
            bordercolor=p["line"],
            insertcolor=p["cyan"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p["field"]), ("focus", p["field_focus"])],
            foreground=[("readonly", p["text"])],
            bordercolor=[("focus", p["cyan"])],
        )
        style.configure(
            "TNotebook",
            background=p["surface"],
            borderwidth=0,
            tabmargins=(8, 6, 8, 0),
        )
        style.configure(
            "TNotebook.Tab",
            padding=(16, 8),
            font=("Segoe UI Semibold", 9),
            background=p["surface_3"],
            foreground=p["muted"],
            bordercolor=p["line"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", p["cyan"]), ("active", "#203142")],
            foreground=[("selected", "#041016"), ("active", p["text"])],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=p["field"],
            background=p["cyan"],
            darkcolor=p["cyan"],
            lightcolor=p["cyan"],
            bordercolor=p["line"],
        )
        style.configure(
            "Treeview",
            background=p["field"],
            foreground=p["text"],
            fieldbackground=p["field"],
            bordercolor=p["line"],
            rowheight=24,
            font=("Segoe UI", 9),
        )
        style.map(
            "Treeview",
            background=[("selected", p["cyan"])],
            foreground=[("selected", "#041016")],
        )
        style.configure(
            "Treeview.Heading",
            background=p["surface_3"],
            foreground=p["cyan"],
            font=("Segoe UI Semibold", 9),
            bordercolor=p["line"],
            relief="flat",
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#203142")],
            foreground=[("active", p["text"])],
        )
        style.configure("TSeparator", background=p["line"])
        style.configure(
            "Section.TLabel",
            font=("Segoe UI Semibold", 9),
            foreground=p["cyan"],
            background=p["surface"],
        )
        style.configure(
            "HeaderTitle.TLabel",
            font=("Segoe UI Semibold", 20),
            foreground=p["text"],
            background=p["app_bg"],
        )
        style.configure(
            "HeaderSub.TLabel",
            font=("Segoe UI", 10),
            foreground=p["muted"],
            background=p["app_bg"],
        )
        style.configure(
            "Signal.TLabel",
            font=("Segoe UI Semibold", 9),
            foreground=p["lime"],
            background=p["app_bg"],
            padding=(10, 5),
        )
        style.configure(
            "StatusLabel.TLabel",
            font=("Segoe UI Semibold", 9),
            foreground=p["lime"],
            background=p["surface_2"],
        )
        style.configure(
            "Footer.TLabel",
            font=("Segoe UI", 8),
            foreground=p["muted"],
            background=p["surface"],
        )
        style.configure(
            "SummaryChip.TLabel",
            font=("Segoe UI Semibold", 9),
            foreground=p["text"],
            background="#0A1B24",
            padding=(12, 6),
            borderwidth=1,
            relief="solid",
        )

    def _build_menu(self) -> None:
        self.root.option_add("*tearOff", False)
        menu_kwargs = {
            "background": _THEME["surface_2"],
            "foreground": _THEME["text"],
            "activebackground": _THEME["cyan"],
            "activeforeground": "#041016",
            "borderwidth": 0,
        }
        menu = Menu(self.root, **menu_kwargs)

        file_menu = Menu(menu, **menu_kwargs)
        file_menu.add_command(label="Choose Drawing PDFs...", command=self._choose_pdfs)
        file_menu.add_command(label="Pick Overrides JSON...", command=self._choose_overrides_file)
        file_menu.add_separator()
        file_menu.add_command(label="Save Output...", command=self._save_output)
        file_menu.add_command(label="Open Results Folder", command=self._open_results_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menu.add_cascade(label="File", menu=file_menu)

        run_menu = Menu(menu, **menu_kwargs)
        run_menu.add_command(label="Quick Start", command=self._quick_start_run)
        run_menu.add_command(label="Submit Async Job", command=self._submit_async_job)
        run_menu.add_command(label="Run Analysis (sync)", command=self._run_analysis)
        run_menu.add_separator()
        run_menu.add_command(label="Refresh Job", command=self._refresh_job)
        run_menu.add_command(label="Load Latest Job", command=self._load_latest_job)
        run_menu.add_command(label="Cancel Job", command=self._cancel_job)
        run_menu.add_separator()
        run_menu.add_command(label="Restart Local API", command=self._restart_local_api_clicked)
        run_menu.add_command(label="Shutdown Local API", command=self._shutdown_local_api_clicked)
        menu.add_cascade(label="Run", menu=run_menu)

        view_menu = Menu(menu, **menu_kwargs)
        view_menu.add_checkbutton(
            label="Beginner Mode",
            variable=self.beginner_mode,
            command=self._toggle_beginner_mode,
        )
        view_menu.add_checkbutton(
            label="Advanced Tools",
            variable=self.show_advanced_tools,
            command=self._toggle_advanced_tools,
        )
        view_menu.add_checkbutton(
            label="Auto Poll Job",
            variable=self.auto_poll_enabled,
            command=self._toggle_auto_poll,
        )
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = Menu(menu, **menu_kwargs)
        help_menu.add_command(label="Control Guide", command=self._show_control_guide)
        menu.add_cascade(label="Help", menu=help_menu)

        self._native_menu = menu
        self.root.configure(menu=menu)

    def _set_native_menu_visible(self, visible: bool) -> None:
        if self._native_menu is None or self._native_menu_visible == visible:
            return
        try:
            self.root.configure(menu=self._native_menu if visible else "")
            self._native_menu_visible = visible
            if visible:
                now = time.monotonic()
                self._menu_visible_since_monotonic = now
                self._menu_last_activity_monotonic = now
            else:
                self._menu_visible_since_monotonic = 0.0
        except Exception:
            return

    def _cancel_native_menu_show(self) -> None:
        if self._menu_show_after_id is None:
            return
        try:
            self.root.after_cancel(self._menu_show_after_id)
        except Exception:
            pass
        self._menu_show_after_id = None

    def _schedule_native_menu_show(self) -> None:
        if self._native_menu_visible:
            return
        if self._menu_show_after_id is not None:
            return
        self._menu_show_after_id = self.root.after(
            int(self._menu_show_delay_ms),
            self._attempt_native_menu_show,
        )

    def _attempt_native_menu_show(self) -> None:
        self._menu_show_after_id = None
        if self._native_menu_visible:
            return
        if not self._pointer_in_menu_hover_zone():
            return
        self._set_native_menu_visible(True)

    def _cancel_native_menu_hide(self) -> None:
        if self._menu_hide_after_id is None:
            return
        try:
            self.root.after_cancel(self._menu_hide_after_id)
        except Exception:
            pass
        self._menu_hide_after_id = None

    def _schedule_native_menu_hide(self) -> None:
        self._cancel_native_menu_hide()
        self._menu_hide_after_id = self.root.after(
            int(self._menu_hide_delay_ms),
            self._attempt_native_menu_hide,
        )

    def _pointer_in_menu_hover_zone(self) -> bool:
        try:
            pointer_y = int(self.root.winfo_pointery()) - int(self.root.winfo_rooty())
        except Exception:
            return False
        return int(self._menu_hover_zone_top_px) <= pointer_y <= int(self._menu_hover_zone_px)

    def _attempt_native_menu_hide(self) -> None:
        self._menu_hide_after_id = None
        if not self._native_menu_visible:
            return
        if self._pointer_in_menu_hover_zone():
            return
        elapsed = time.monotonic() - float(self._menu_last_activity_monotonic)
        if elapsed < (float(self._menu_hide_delay_ms) / 1000.0):
            self._schedule_native_menu_hide()
            return
        visible_elapsed = time.monotonic() - float(self._menu_visible_since_monotonic)
        if visible_elapsed < (float(self._menu_min_visible_ms) / 1000.0):
            self._schedule_native_menu_hide()
            return
        self._set_native_menu_visible(False)

    def _on_native_menu_activity(self, _event: object = None) -> None:
        self._menu_last_activity_monotonic = time.monotonic()
        self._cancel_native_menu_show()
        self._cancel_native_menu_hide()
        self._set_native_menu_visible(True)

    def _on_root_motion_menu(self, event: object) -> None:
        if self._pointer_in_menu_hover_zone():
            self._cancel_native_menu_hide()
            if self._native_menu_visible:
                self._menu_last_activity_monotonic = time.monotonic()
                return
            self._schedule_native_menu_show()
            return
        self._cancel_native_menu_show()
        if self._native_menu_visible:
            self._schedule_native_menu_hide()

    def _on_root_leave_menu(self, _event: object = None) -> None:
        self._cancel_native_menu_show()
        if self._native_menu_visible:
            self._schedule_native_menu_hide()

    def _enable_hover_menu_mode(self) -> None:
        self._set_native_menu_visible(False)
        self.root.bind("<Motion>", self._on_root_motion_menu, add="+")
        self.root.bind("<Leave>", self._on_root_leave_menu, add="+")
        self.root.bind_all("<<MenuSelect>>", self._on_native_menu_activity, add="+")

    def _build_scrollable_surface(
        self,
        *,
        parent: object,
        container_style: str,
        padding: tuple[int, int, int, int],
        canvas_background: str,
        min_width: int,
        min_height: int,
    ) -> tuple[Canvas, ttk.Frame]:
        host = ttk.Frame(parent, style=container_style)
        host.pack(fill="both", expand=True)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)

        canvas = Canvas(
            host,
            background=canvas_background,
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(host, orient="horizontal", command=canvas.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        container = ttk.Frame(canvas, padding=padding, style=container_style)
        window_id = canvas.create_window((0, 0), window=container, anchor="nw")

        def _sync_scroll_region(_event: object = None) -> None:
            bbox = canvas.bbox("all")
            if bbox is not None:
                canvas.configure(scrollregion=bbox)

        def _sync_window_size(event: object) -> None:
            viewport_width = int(getattr(event, "width", 0))
            viewport_height = int(getattr(event, "height", 0))
            target_width = max(container.winfo_reqwidth(), viewport_width, min_width)
            target_height = max(container.winfo_reqheight(), viewport_height, min_height)
            canvas.itemconfigure(window_id, width=target_width, height=target_height)
            _sync_scroll_region()

        container.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_window_size)
        self._bind_mousewheel_scrollable_canvas(canvas)
        return canvas, container

    def _build_ui(self) -> None:
        p = _THEME
        self.main_scroll_canvas, container = self._build_scrollable_surface(
            parent=self.root,
            container_style="App.TFrame",
            padding=(18, 16, 18, 16),
            canvas_background=p["app_bg"],
            min_width=1200,
            min_height=740,
        )
        container.columnconfigure(0, weight=1)
        container.rowconfigure(4, weight=1)

        self._build_menu()

        header = ttk.Frame(container, style="Hero.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="EstimateForge Command Center", style="HeaderTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Construction takeoff, scope intelligence, benchmark gates, and handoff-ready estimating",
            style="HeaderSub.TLabel",
        ).grid(row=1, column=0, sticky="w")
        ttk.Label(header, text="MODEL PIPELINE ONLINE", style="Signal.TLabel").grid(
            row=0, column=1, sticky="e", padx=(16, 0)
        )
        ttk.Label(header, text="High-contrast field command UI", style="HeaderSub.TLabel").grid(
            row=1, column=1, sticky="e", padx=(16, 0)
        )

        self.construction_banner = Canvas(
            container,
            height=78,
            background=p["app_bg"],
            highlightthickness=2,
            highlightbackground=p["cyan"],
        )
        self.construction_banner.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.construction_banner.bind(
            "<Configure>",
            lambda event: self._draw_construction_banner(event.widget),
        )
        self._draw_construction_banner(self.construction_banner)

        summary_row = ttk.Frame(container, style="App.TFrame")
        summary_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        summary_row.columnconfigure(3, weight=1)
        ttk.Label(summary_row, textvariable=self.header_mode_text, style="SummaryChip.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(summary_row, textvariable=self.header_job_text, style="SummaryChip.TLabel").grid(
            row=0, column=1, sticky="w", padx=(0, 12)
        )
        ttk.Label(summary_row, textvariable=self.header_files_text, style="SummaryChip.TLabel").grid(
            row=0, column=2, sticky="w"
        )

        project_bar = ttk.Frame(container, style="Panel.TFrame", padding=(10, 8))
        project_bar.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        project_bar.columnconfigure(1, weight=1)
        ttk.Label(project_bar, text="Project Library", style="FormLabel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(2, 8)
        )
        self.project_selector_combo = ttk.Combobox(
            project_bar,
            textvariable=self.active_project_name,
            state="readonly",
            width=38,
            values=[],
        )
        self.project_selector_combo.grid(row=0, column=1, sticky="ew")
        self.project_selector_combo.bind("<<ComboboxSelected>>", self._load_selected_project_profile_event)
        ttk.Button(
            project_bar,
            text="Load Saved Project",
            command=self._load_selected_project_profile,
            style="Accent.TButton",
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            project_bar,
            text="Open Saved Job",
            command=self._open_saved_project_job,
            style="Primary.TButton",
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Button(
            project_bar,
            text="Save Project Snapshot",
            command=self._save_project_profile_from_current,
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Button(
            project_bar,
            text="Project Setup Window",
            command=self._open_project_setup_window,
            style="Primary.TButton",
        ).grid(row=0, column=5, sticky="w", padx=(8, 0))
        ttk.Button(
            project_bar,
            text="New Project",
            command=self._start_new_project_profile,
        ).grid(row=0, column=6, sticky="w", padx=(8, 0))

        frame = ttk.Frame(container, padding=14, style="Panel.TFrame")
        frame.grid(row=4, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        self.field_label_api_url = ttk.Label(frame, text="API URL", style="FormLabel.TLabel")
        self.field_label_api_url.grid(row=0, column=0, sticky="w")
        self._field_label_widgets["api_url"] = self.field_label_api_url
        api_row = ttk.Frame(frame)
        api_row.grid(row=0, column=1, sticky="ew")
        api_row.columnconfigure(0, weight=1)
        api_url_entry = ttk.Entry(api_row, textvariable=self.api_url, width=58)
        api_url_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(api_row, text="Start Local API", command=self._start_local_api_clicked, style="Accent.TButton").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(api_row, text="Restart API", command=self._restart_local_api_clicked).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(api_row, text="Shutdown API", command=self._shutdown_local_api_clicked).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Button(api_row, text="Check API Health", command=self._check_api_health_clicked).grid(
            row=0, column=4, sticky="w", padx=(8, 0)
        )
        ttk.Button(api_row, text="Control Guide", command=self._show_control_guide).grid(
            row=0, column=5, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(
            api_row,
            text="Beginner Mode",
            variable=self.beginner_mode,
            command=self._toggle_beginner_mode,
        ).grid(row=0, column=6, sticky="w", padx=(8, 0))
        ttk.Checkbutton(
            api_row,
            text="Advanced Tools",
            variable=self.show_advanced_tools,
            command=self._toggle_advanced_tools,
        ).grid(row=0, column=7, sticky="w", padx=(8, 0))
        ttk.Label(api_row, text="Theme", style="FormLabel.TLabel").grid(
            row=0, column=8, sticky="e", padx=(14, 4)
        )
        self.theme_combo = ttk.Combobox(
            api_row,
            textvariable=self.theme_preset,
            state="readonly",
            width=18,
            values=_THEME_PRESET_OPTIONS,
        )
        self.theme_combo.grid(row=0, column=9, sticky="w")
        ttk.Checkbutton(
            api_row,
            text="Dark Mode",
            variable=self.dark_mode_enabled,
        ).grid(row=0, column=10, sticky="w", padx=(8, 0))
        ttk.Checkbutton(
            api_row,
            text="Animate Banner",
            variable=self.banner_animation_enabled,
        ).grid(row=0, column=11, sticky="w", padx=(8, 0))

        self.field_label_api_key = ttk.Label(frame, text="API Key (optional)", style="FormLabel.TLabel")
        self.field_label_api_key.grid(row=1, column=0, sticky="w")
        self._field_label_widgets["api_key"] = self.field_label_api_key
        security_row = ttk.Frame(frame)
        security_row.grid(row=1, column=1, sticky="ew")
        security_row.columnconfigure(0, weight=1)
        api_key_entry = ttk.Entry(security_row, textvariable=self.api_key, width=46, show="*")
        api_key_entry.grid(row=0, column=0, sticky="ew")
        self.field_label_tenant_id = ttk.Label(security_row, text="Tenant ID", style="FormLabel.TLabel")
        self.field_label_tenant_id.grid(row=0, column=1, sticky="w", padx=(10, 4))
        self._field_label_widgets["tenant_id"] = self.field_label_tenant_id
        tenant_id_entry = ttk.Entry(security_row, textvariable=self.tenant_id, width=22)
        tenant_id_entry.grid(row=0, column=2, sticky="w")

        self.field_label_analysis_mode = ttk.Label(frame, text="Analysis Mode", style="FormLabel.TLabel")
        self.field_label_analysis_mode.grid(row=2, column=0, sticky="w")
        self._field_label_widgets["analysis_mode"] = self.field_label_analysis_mode
        self.analysis_mode_combo = ttk.Combobox(
            frame,
            values=self.analysis_mode_catalog,
            textvariable=self.analysis_mode,
            state="readonly",
            width=20,
        )
        self.analysis_mode_combo.grid(row=2, column=1, sticky="w")

        self.field_label_selected_trades = ttk.Label(frame, text="Selected Trades (CSV)", style="FormLabel.TLabel")
        self.field_label_selected_trades.grid(row=3, column=0, sticky="w")
        self._field_label_widgets["selected_trades"] = self.field_label_selected_trades
        selected_trades_row = ttk.Frame(frame)
        selected_trades_row.grid(row=3, column=1, sticky="ew")
        selected_trades_row.columnconfigure(0, weight=1)
        selected_trades_entry = ttk.Entry(selected_trades_row, textvariable=self.selected_trades, width=52)
        selected_trades_entry.grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(selected_trades_row, text="Load Trades", command=self._load_trade_catalog).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(
            selected_trades_row,
            text="Validate Trades",
            command=self._validate_selected_trades_clicked,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.field_label_sheet_overrides = ttk.Label(frame, text="Sheet Overrides JSON", style="FormLabel.TLabel")
        self.field_label_sheet_overrides.grid(row=4, column=0, sticky="w")
        self._field_label_widgets["overrides_path"] = self.field_label_sheet_overrides
        overrides_row = ttk.Frame(frame)
        overrides_row.grid(row=4, column=1, sticky="ew")
        overrides_row.columnconfigure(0, weight=1)
        overrides_entry = ttk.Entry(overrides_row, textvariable=self.sheet_overrides_path, width=58)
        overrides_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(overrides_row, text="Browse", command=self._choose_overrides_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        self.field_label_current_job = ttk.Label(frame, text="Current Job ID", style="FormLabel.TLabel")
        self.field_label_current_job.grid(row=5, column=0, sticky="w")
        self._field_label_widgets["current_job"] = self.field_label_current_job
        current_job_entry = ttk.Entry(frame, textvariable=self.current_job_id, width=68)
        current_job_entry.grid(row=5, column=1, sticky="ew")

        self.field_label_notes = ttk.Label(frame, text="Notes", style="FormLabel.TLabel")
        self.field_label_notes.grid(row=6, column=0, sticky="w")
        self._field_label_widgets["notes"] = self.field_label_notes
        notes_entry = ttk.Entry(frame, textvariable=self.notes, width=68)
        notes_entry.grid(row=6, column=1, sticky="ew")

        self._inline_setup_widgets = [
            self.field_label_api_url,
            api_row,
            self.field_label_api_key,
            security_row,
            self.field_label_analysis_mode,
            self.analysis_mode_combo,
            self.field_label_selected_trades,
            selected_trades_row,
            self.field_label_sheet_overrides,
            overrides_row,
            self.field_label_current_job,
            current_job_entry,
            self.field_label_notes,
            notes_entry,
        ]

        self.actions_notebook = ttk.Notebook(frame)
        self.actions_notebook.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 8))
        workflow_tab = ttk.Frame(self.actions_notebook, padding=8)
        quality_tab = ttk.Frame(self.actions_notebook, padding=8)
        operations_tab = ttk.Frame(self.actions_notebook, padding=8)
        calculators_tab = ttk.Frame(self.actions_notebook, padding=8)
        self.actions_notebook.add(workflow_tab, text="Workflow")
        self.actions_notebook.add(quality_tab, text="Quality")
        self.actions_notebook.add(operations_tab, text="Operations")
        self.actions_notebook.add(calculators_tab, text="Calculators")
        self._advanced_tab_widgets = [(quality_tab, "Quality"), (operations_tab, "Operations")]

        workflow_quick_path = ttk.LabelFrame(
            workflow_tab,
            text="Estimator Run Path",
            padding=8,
        )
        workflow_quick_path.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for col in range(4):
            workflow_quick_path.columnconfigure(col, weight=1)
        ttk.Label(
            workflow_quick_path,
            text="Use this order for fastest estimating: load drawings, confirm work types, then run.",
            style="FormLabel.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Button(
            workflow_quick_path,
            text="1) Load Drawings",
            command=self._choose_pdfs,
            style="Primary.TButton",
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(
            workflow_quick_path,
            text="2) Confirm Work Types",
            command=self._discover_trade_options_from_drawings,
            style="Accent.TButton",
        ).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(
            workflow_quick_path,
            text="3) Run Takeoff",
            command=self._quick_start_run,
            style="Primary.TButton",
        ).grid(row=1, column=2, sticky="ew", padx=4, pady=4)
        ttk.Label(
            workflow_quick_path,
            textvariable=self.trade_selection_hint_text,
            style="SummaryChip.TLabel",
        ).grid(row=1, column=3, sticky="ew", padx=4, pady=4)

        self.guided_flow_frame = ttk.LabelFrame(
            workflow_tab,
            text="Guided Start (Step-by-Step)",
            padding=8,
        )
        self.guided_flow_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for col in range(4):
            self.guided_flow_frame.columnconfigure(col, weight=1)

        ttk.Label(
            self.guided_flow_frame,
            textvariable=self.guided_step_title,
            style="Section.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        ttk.Label(
            self.guided_flow_frame,
            textvariable=self.guided_step_detail,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 6))

        strategy_row = ttk.Frame(self.guided_flow_frame)
        strategy_row.grid(row=2, column=0, columnspan=4, sticky="ew")
        for col in range(3):
            strategy_row.columnconfigure(col, weight=1)
        ttk.Radiobutton(
            strategy_row,
            text="All Trades",
            variable=self.guided_trade_strategy,
            value="all",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            strategy_row,
            text="Analyze Drawings for Available Trades",
            variable=self.guided_trade_strategy,
            value="auto",
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            strategy_row,
            text="I Will Choose Work Types",
            variable=self.guided_trade_strategy,
            value="selected",
        ).grid(row=0, column=2, sticky="w")

        self.guided_selected_frame = ttk.LabelFrame(
            self.guided_flow_frame,
            text="If choosing work types",
            padding=6,
        )
        self.guided_selected_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.guided_selected_frame.columnconfigure(0, weight=1)
        selected_inline_row = ttk.Frame(self.guided_selected_frame)
        selected_inline_row.grid(row=0, column=0, sticky="ew")
        selected_inline_row.columnconfigure(0, weight=1)
        ttk.Entry(
            selected_inline_row,
            textvariable=self.selected_trades,
            width=54,
            state="readonly",
        ).grid(row=0, column=0, sticky="ew")
        self.guided_discover_button = ttk.Button(
            selected_inline_row,
            text="Analyze Drawings for Trade Options",
            command=self._discover_trade_options_from_drawings,
            style="Accent.TButton",
        )
        self.guided_discover_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            selected_inline_row,
            text="Load Trades",
            command=self._load_trade_catalog,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            selected_inline_row,
            text="Validate Trades",
            command=self._validate_selected_trades_clicked,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        self.guided_trade_options_frame = ttk.Frame(self.guided_selected_frame)
        self.guided_trade_options_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(
            self.guided_trade_options_frame,
            text="Selectable Work Types (click to include):",
            style="FormLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")

        self.guided_objective_frame = ttk.LabelFrame(
            self.guided_flow_frame,
            text="Run Objective",
            padding=6,
        )
        self.guided_objective_frame.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        objective_row = ttk.Frame(self.guided_objective_frame)
        objective_row.grid(row=0, column=0, sticky="ew")
        for col in range(3):
            objective_row.columnconfigure(col, weight=1)
        ttk.Radiobutton(
            objective_row,
            text="Takeoff + Estimation",
            variable=self.guided_run_objective,
            value="takeoff_and_estimation",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            objective_row,
            text="Takeoff Only",
            variable=self.guided_run_objective,
            value="takeoff_only",
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Radiobutton(
            objective_row,
            text="Estimate Man-Hours Only",
            variable=self.guided_run_objective,
            value="manhours_only",
        ).grid(row=0, column=2, sticky="w")

        guided_actions_row = ttk.Frame(self.guided_flow_frame)
        guided_actions_row.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        guided_actions_row.columnconfigure(4, weight=1)
        self.guided_back_button = ttk.Button(
            guided_actions_row,
            text="Guided Back",
            command=self._guided_back,
        )
        self.guided_back_button.grid(row=0, column=0, sticky="w")
        self.guided_proceed_button = ttk.Button(
            guided_actions_row,
            text="Guided Proceed",
            style="Primary.TButton",
            command=self._guided_proceed,
        )
        self.guided_proceed_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.guided_execute_button = ttk.Button(
            guided_actions_row,
            text="Run Guided Step",
            style="Primary.TButton",
            command=self._guided_execute,
        )
        self.guided_execute_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.guided_skip_button = ttk.Button(
            guided_actions_row,
            text="Skip to Full Interface",
            command=self._guided_skip_to_full,
        )
        self.guided_skip_button.grid(row=0, column=3, sticky="w", padx=(8, 0))

        workflow_run = ttk.LabelFrame(workflow_tab, text="Run Drawings", padding=8)
        workflow_run.grid(row=2, column=0, sticky="ew")
        for col in range(6):
            workflow_run.columnconfigure(col, weight=1)
        ttk.Button(workflow_run, text="Choose PDFs", command=self._choose_pdfs).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(
            workflow_run,
            text="Quick Start",
            style="Primary.TButton",
            command=self._quick_start_run,
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(
            workflow_run,
            text="Submit Async Job",
            style="Primary.TButton",
            command=self._submit_async_job,
        ).grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        ttk.Button(workflow_run, text="Run Analysis", command=self._run_analysis).grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        ttk.Button(workflow_run, text="Refresh Job", command=self._refresh_job).grid(row=0, column=4, sticky="ew", padx=4, pady=4)
        ttk.Button(workflow_run, text="Load Latest Job", command=self._load_latest_job).grid(row=0, column=5, sticky="ew", padx=4, pady=4)
        ttk.Button(workflow_run, text="Rerun Job", command=self._rerun_job).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(
            workflow_run,
            text="Rerun Recommended",
            command=self._rerun_job_with_recommendation,
        ).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(workflow_run, text="Cancel Job", command=self._cancel_job).grid(row=1, column=2, sticky="ew", padx=4, pady=4)
        ttk.Checkbutton(
            workflow_run,
            text="Auto Poll Job",
            variable=self.auto_poll_enabled,
            command=self._toggle_auto_poll,
        ).grid(row=1, column=3, sticky="w", padx=4, pady=4)
        ttk.Button(workflow_run, text="Save Output", command=self._save_output).grid(row=1, column=4, sticky="ew", padx=4, pady=4)
        ttk.Button(workflow_run, text="Open Results Folder", command=self._open_results_folder).grid(
            row=1, column=5, sticky="ew", padx=4, pady=4
        )

        workflow_benchmark = ttk.LabelFrame(workflow_tab, text="Full Quality Flow", padding=8)
        workflow_benchmark.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        workflow_benchmark.columnconfigure(0, weight=1)
        ttk.Button(
            workflow_benchmark,
            text="Run End-to-End Benchmark",
            command=self._run_end_to_end_benchmark,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=4)

        quality_templates = ttk.LabelFrame(quality_tab, text="Templates & Review", padding=8)
        quality_templates.grid(row=0, column=0, sticky="ew")
        for col in range(4):
            quality_templates.columnconfigure(col, weight=1)
        ttk.Checkbutton(
            quality_templates,
            text="Template Include All Sheets",
            variable=self.include_all_template,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Button(quality_templates, text="Get Review Queue", command=self._get_review_queue).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_templates, text="Export Overrides Template", command=self._export_overrides_template).grid(
            row=0, column=2, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_templates, text="Export Benchmark Template", command=self._export_benchmark_template).grid(
            row=0, column=3, sticky="ew", padx=4, pady=4
        )

        quality_compare = ttk.LabelFrame(quality_tab, text="Benchmarks", padding=8)
        quality_compare.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for col in range(5):
            quality_compare.columnconfigure(col, weight=1)
        ttk.Checkbutton(
            quality_compare,
            text="Benchmark Include Unmapped",
            variable=self.include_unmapped_benchmark,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Button(quality_compare, text="Run Baseline Benchmark", command=self._run_baseline_benchmark).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Show Benchmark History", command=self._show_benchmark_history).grid(
            row=0, column=2, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Compare Reports", command=self._compare_benchmark_reports).grid(
            row=0, column=3, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Compare Latest Reports", command=self._compare_latest_benchmark_reports).grid(
            row=0, column=4, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Latest Trend Snapshot", command=self._show_benchmark_trend_snapshot).grid(
            row=1, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Score Timeline", command=self._show_benchmark_score_timeline).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Evaluate Gate", command=self._evaluate_benchmark_quality_gate).grid(
            row=1, column=2, sticky="ew", padx=4, pady=4
        )
        ttk.Button(quality_compare, text="Benchmark Dashboard", command=self._show_benchmark_dashboard).grid(
            row=1, column=3, sticky="ew", padx=4, pady=4
        )

        operations_jobs = ttk.LabelFrame(operations_tab, text="Operations", padding=8)
        operations_jobs.grid(row=0, column=0, sticky="ew")
        for col in range(3):
            operations_jobs.columnconfigure(col, weight=1)
        ttk.Button(operations_jobs, text="Job Ops Snapshot", command=self._show_job_ops_snapshot).grid(
            row=0, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(operations_jobs, text="Job Ops Gate", command=self._evaluate_job_ops_gate).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(operations_jobs, text="Readiness Report", command=self._get_readiness_report).grid(
            row=0, column=2, sticky="ew", padx=4, pady=4
        )
        ttk.Button(operations_jobs, text="Trade Recommendation", command=self._get_trade_recommendation).grid(
            row=1, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(operations_jobs, text="Trade Coverage", command=self._get_trade_coverage).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4
        )

        prune_row = ttk.LabelFrame(operations_tab, text="Data Cleanup", padding=8)
        prune_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        prune_row.columnconfigure(12, weight=1)
        self.field_label_prune_statuses = ttk.Label(prune_row, text="Prune Statuses", style="FormLabel.TLabel")
        self.field_label_prune_statuses.grid(row=0, column=0, sticky="w")
        self._field_label_widgets["prune_statuses"] = self.field_label_prune_statuses
        prune_statuses_entry = ttk.Entry(prune_row, textvariable=self.prune_statuses, width=28)
        prune_statuses_entry.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.field_label_prune_older_than = ttk.Label(prune_row, text="Older Than (h)", style="FormLabel.TLabel")
        self.field_label_prune_older_than.grid(row=0, column=2, sticky="w", padx=(12, 0))
        self._field_label_widgets["prune_older_than"] = self.field_label_prune_older_than
        prune_older_than_entry = ttk.Entry(prune_row, textvariable=self.prune_older_than_hours, width=8)
        prune_older_than_entry.grid(row=0, column=3, sticky="w", padx=(6, 0))
        self.field_label_prune_limit = ttk.Label(prune_row, text="Limit", style="FormLabel.TLabel")
        self.field_label_prune_limit.grid(row=0, column=4, sticky="w", padx=(12, 0))
        self._field_label_widgets["prune_limit"] = self.field_label_prune_limit
        prune_limit_entry = ttk.Entry(prune_row, textvariable=self.prune_limit, width=8)
        prune_limit_entry.grid(row=0, column=5, sticky="w", padx=(6, 0))
        ttk.Checkbutton(
            prune_row,
            text="Cleanup Uploads",
            variable=self.prune_cleanup_uploads,
        ).grid(row=0, column=6, sticky="w", padx=(12, 0))
        ttk.Button(prune_row, text="Prune Dry Run", command=self._prune_jobs_dry_run).grid(
            row=0, column=7, sticky="w", padx=(8, 0)
        )
        ttk.Button(prune_row, text="Prune Apply", command=self._prune_jobs_apply).grid(
            row=0, column=8, sticky="w", padx=(8, 0)
        )

        calculators_tab.columnconfigure(0, weight=1)
        calculators_tab.rowconfigure(0, weight=1)
        calc_scroll_frame = ttk.Frame(calculators_tab)
        calc_scroll_frame.grid(row=0, column=0, sticky="nsew")
        calc_scroll_frame.columnconfigure(0, weight=1)
        calc_scroll_frame.rowconfigure(0, weight=1)

        self.calculators_canvas = Canvas(
            calc_scroll_frame,
            background=p["surface"],
            highlightthickness=0,
            borderwidth=0,
            yscrollincrement=14,
            xscrollincrement=14,
        )
        self.calculators_canvas.grid(row=0, column=0, sticky="nsew")
        calc_vscroll = ttk.Scrollbar(
            calc_scroll_frame,
            orient="vertical",
            command=self.calculators_canvas.yview,
        )
        calc_vscroll.grid(row=0, column=1, sticky="ns")
        calc_hscroll = ttk.Scrollbar(
            calc_scroll_frame,
            orient="horizontal",
            command=self.calculators_canvas.xview,
        )
        calc_hscroll.grid(row=1, column=0, sticky="ew")
        self.calculators_canvas.configure(
            yscrollcommand=calc_vscroll.set,
            xscrollcommand=calc_hscroll.set,
        )

        calculators_surface = ttk.Frame(self.calculators_canvas, padding=(4, 4, 8, 8))
        calc_window = self.calculators_canvas.create_window(
            (0, 0),
            window=calculators_surface,
            anchor="nw",
        )

        calculators_surface.bind(
            "<Configure>",
            lambda _event: self.calculators_canvas.configure(
                scrollregion=self.calculators_canvas.bbox("all")
            ),
        )
        def _sync_calculator_surface(event: object) -> None:
            viewport_width = int(getattr(event, "width", 0))
            target_width = max(calculators_surface.winfo_reqwidth(), viewport_width)
            self.calculators_canvas.itemconfigure(calc_window, width=target_width)

        self.calculators_canvas.bind("<Configure>", _sync_calculator_surface)
        self._bind_mousewheel_scrollable_canvas(self.calculators_canvas)

        calculators_surface.columnconfigure(0, weight=1)
        ttk.Label(
            calculators_surface,
            text="Trade Calculators: field math for piping, concrete, sheet metal/HVAC, earthwork, and framing.",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        pipe_frame = ttk.LabelFrame(
            calculators_surface,
            text="Industrial Pipe / Feet-Inches Calculator",
            padding=10,
        )
        pipe_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for col in range(8):
            pipe_frame.columnconfigure(col, weight=1)
        ttk.Label(pipe_frame, text="Length (ft)").grid(row=0, column=0, sticky="w")
        ttk.Entry(pipe_frame, textvariable=self.pipe_length_feet, width=8).grid(row=1, column=0, sticky="w")
        ttk.Label(pipe_frame, text="Length (in)").grid(row=0, column=1, sticky="w")
        ttk.Entry(pipe_frame, textvariable=self.pipe_length_inches, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(pipe_frame, text="Run Count").grid(row=0, column=2, sticky="w")
        ttk.Entry(pipe_frame, textvariable=self.pipe_run_count, width=10).grid(row=1, column=2, sticky="w")
        ttk.Label(pipe_frame, text="Waste %").grid(row=0, column=3, sticky="w")
        ttk.Entry(pipe_frame, textvariable=self.pipe_waste_percent, width=10).grid(row=1, column=3, sticky="w")
        ttk.Button(
            pipe_frame,
            text="Calc Pipe Takeoff",
            command=self._recalc_pipe_takeoff,
            style="Primary.TButton",
        ).grid(row=1, column=4, sticky="w", padx=(12, 0))
        ttk.Button(
            pipe_frame,
            text="Open Full Tool",
            command=lambda: self._open_full_calculator("pipe"),
        ).grid(row=1, column=5, sticky="w", padx=(8, 0))
        ttk.Label(
            pipe_frame,
            textvariable=self.pipe_calc_result,
        ).grid(row=1, column=6, columnspan=2, sticky="w", padx=(8, 0))

        concrete_frame = ttk.LabelFrame(
            calculators_surface,
            text="Concrete and Gravel Calculator",
            padding=10,
        )
        concrete_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for col in range(8):
            concrete_frame.columnconfigure(col, weight=1)
        ttk.Label(concrete_frame, text="Length (ft)").grid(row=0, column=0, sticky="w")
        ttk.Entry(concrete_frame, textvariable=self.concrete_length_feet, width=10).grid(row=1, column=0, sticky="w")
        ttk.Label(concrete_frame, text="Width (ft)").grid(row=0, column=1, sticky="w")
        ttk.Entry(concrete_frame, textvariable=self.concrete_width_feet, width=10).grid(row=1, column=1, sticky="w")
        ttk.Label(concrete_frame, text="Depth (in)").grid(row=0, column=2, sticky="w")
        ttk.Entry(concrete_frame, textvariable=self.concrete_depth_inches, width=10).grid(row=1, column=2, sticky="w")
        ttk.Label(concrete_frame, text="Waste %").grid(row=0, column=3, sticky="w")
        ttk.Entry(concrete_frame, textvariable=self.concrete_waste_percent, width=10).grid(row=1, column=3, sticky="w")
        ttk.Button(
            concrete_frame,
            text="Calc Concrete/Gravel",
            command=self._recalc_concrete_takeoff,
            style="Primary.TButton",
        ).grid(row=1, column=4, sticky="w", padx=(12, 0))
        ttk.Button(
            concrete_frame,
            text="Open Full Tool",
            command=lambda: self._open_full_calculator("concrete"),
        ).grid(row=1, column=5, sticky="w", padx=(8, 0))
        ttk.Label(
            concrete_frame,
            textvariable=self.concrete_calc_result,
        ).grid(row=1, column=6, columnspan=2, sticky="w", padx=(8, 0))

        hvac_frame = ttk.LabelFrame(
            calculators_surface,
            text="Sheet Metal / HVAC Calculator",
            padding=10,
        )
        hvac_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        for col in range(8):
            hvac_frame.columnconfigure(col, weight=1)
        ttk.Label(hvac_frame, text="Duct Diameter (in)").grid(row=0, column=0, sticky="w")
        ttk.Entry(hvac_frame, textvariable=self.hvac_diameter_inches, width=10).grid(row=1, column=0, sticky="w")
        ttk.Label(hvac_frame, text="Run Length (ft)").grid(row=0, column=1, sticky="w")
        ttk.Entry(hvac_frame, textvariable=self.hvac_run_length_feet, width=10).grid(row=1, column=1, sticky="w")
        ttk.Label(hvac_frame, text="Run Count").grid(row=0, column=2, sticky="w")
        ttk.Entry(hvac_frame, textvariable=self.hvac_run_count, width=10).grid(row=1, column=2, sticky="w")
        ttk.Label(hvac_frame, text="Waste %").grid(row=0, column=3, sticky="w")
        ttk.Entry(hvac_frame, textvariable=self.hvac_waste_percent, width=10).grid(row=1, column=3, sticky="w")
        ttk.Button(
            hvac_frame,
            text="Calc HVAC Sheet-Metal",
            command=self._recalc_hvac_takeoff,
            style="Primary.TButton",
        ).grid(row=1, column=4, sticky="w", padx=(12, 0))
        ttk.Button(
            hvac_frame,
            text="Open Full Tool",
            command=lambda: self._open_full_calculator("hvac"),
        ).grid(row=1, column=5, sticky="w", padx=(8, 0))
        ttk.Label(
            hvac_frame,
            textvariable=self.hvac_calc_result,
        ).grid(row=1, column=6, columnspan=2, sticky="w", padx=(8, 0))

        heavy_frame = ttk.LabelFrame(
            calculators_surface,
            text="Heavy Earthwork Calculator",
            padding=10,
        )
        heavy_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        for col in range(8):
            heavy_frame.columnconfigure(col, weight=1)
        ttk.Label(heavy_frame, text="Area (sq ft)").grid(row=0, column=0, sticky="w")
        ttk.Entry(heavy_frame, textvariable=self.heavy_area_sqft, width=10).grid(row=1, column=0, sticky="w")
        ttk.Label(heavy_frame, text="Depth (in)").grid(row=0, column=1, sticky="w")
        ttk.Entry(heavy_frame, textvariable=self.heavy_depth_inches, width=10).grid(row=1, column=1, sticky="w")
        ttk.Label(heavy_frame, text="Swell %").grid(row=0, column=2, sticky="w")
        ttk.Entry(heavy_frame, textvariable=self.heavy_swell_percent, width=10).grid(row=1, column=2, sticky="w")
        ttk.Button(
            heavy_frame,
            text="Calc Earthwork",
            command=self._recalc_heavy_takeoff,
            style="Primary.TButton",
        ).grid(row=1, column=4, sticky="w", padx=(12, 0))
        ttk.Button(
            heavy_frame,
            text="Open Full Tool",
            command=lambda: self._open_full_calculator("heavy"),
        ).grid(row=1, column=5, sticky="w", padx=(8, 0))
        ttk.Label(
            heavy_frame,
            textvariable=self.heavy_calc_result,
        ).grid(row=1, column=6, columnspan=2, sticky="w", padx=(8, 0))

        carpentry_frame = ttk.LabelFrame(
            calculators_surface,
            text="Carpentry Framing Calculator",
            padding=10,
        )
        carpentry_frame.grid(row=5, column=0, sticky="ew")
        for col in range(8):
            carpentry_frame.columnconfigure(col, weight=1)
        ttk.Label(carpentry_frame, text="Wall Length (ft)").grid(row=0, column=0, sticky="w")
        ttk.Entry(
            carpentry_frame,
            textvariable=self.carpentry_wall_length_feet,
            width=10,
        ).grid(row=1, column=0, sticky="w")
        ttk.Label(carpentry_frame, text="Wall Height (ft)").grid(row=0, column=1, sticky="w")
        ttk.Entry(
            carpentry_frame,
            textvariable=self.carpentry_wall_height_feet,
            width=10,
        ).grid(row=1, column=1, sticky="w")
        ttk.Label(carpentry_frame, text="Stud Spacing (in)").grid(row=0, column=2, sticky="w")
        ttk.Entry(
            carpentry_frame,
            textvariable=self.carpentry_stud_spacing_inches,
            width=10,
        ).grid(row=1, column=2, sticky="w")
        ttk.Label(carpentry_frame, text="Waste %").grid(row=0, column=3, sticky="w")
        ttk.Entry(
            carpentry_frame,
            textvariable=self.carpentry_waste_percent,
            width=10,
        ).grid(row=1, column=3, sticky="w")
        ttk.Button(
            carpentry_frame,
            text="Calc Carpentry",
            command=self._recalc_carpentry_takeoff,
            style="Primary.TButton",
        ).grid(row=1, column=4, sticky="w", padx=(12, 0))
        ttk.Button(
            carpentry_frame,
            text="Open Full Tool",
            command=lambda: self._open_full_calculator("carpentry"),
        ).grid(row=1, column=5, sticky="w", padx=(8, 0))
        ttk.Label(
            carpentry_frame,
            textvariable=self.carpentry_calc_result,
        ).grid(row=1, column=6, columnspan=2, sticky="w", padx=(8, 0))

        self._recalc_pipe_takeoff()
        self._recalc_concrete_takeoff()
        self._recalc_hvac_takeoff()
        self._recalc_heavy_takeoff()
        self._recalc_carpentry_takeoff()

        self.files_label = ttk.Label(frame, text="No files selected.", style="StatusLabel.TLabel")
        self.files_label.grid(row=8, column=0, columnspan=2, sticky="w")

        files_summary_frame = ttk.Frame(frame)
        files_summary_frame.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        files_summary_frame.columnconfigure(0, weight=1)
        self.files_list = Text(
            files_summary_frame,
            height=5,
            wrap="none",
            background=p["field"],
            foreground=p["text"],
            insertbackground=p["cyan"],
            selectbackground=p["cyan"],
            selectforeground="#041016",
            padx=6,
            pady=6,
            font=("Segoe UI", 9),
            width=1,
        )
        self.files_list.grid(row=0, column=0, sticky="ew")
        self.files_list_y_scroll = ttk.Scrollbar(
            files_summary_frame, orient="vertical", command=self.files_list.yview
        )
        self.files_list_y_scroll.grid(row=0, column=1, sticky="ns")
        self.files_list.configure(yscrollcommand=self.files_list_y_scroll.set)
        self.files_list.configure(state="disabled")

        status_strip = ttk.Frame(frame, padding=(10, 8), style="Status.TFrame")
        status_strip.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        status_strip.columnconfigure(1, weight=1)
        ttk.Label(status_strip, text="Status:", style="StatusLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status_strip, textvariable=self.status_text, style="StatusLabel.TLabel").grid(
            row=0, column=1, sticky="w"
        )

        progress_row = ttk.Frame(frame)
        progress_row.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        progress_row.columnconfigure(1, weight=1)
        progress_row.columnconfigure(2, weight=1)
        self.request_progress_label = ttk.Label(progress_row, textvariable=self.request_progress_text)
        self.request_progress_label.grid(row=0, column=0, sticky="w")
        self.request_progress_bar = ttk.Progressbar(progress_row, mode="indeterminate", length=260)
        self.request_progress_bar.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.run_phase_label = ttk.Label(progress_row, textvariable=self.run_phase_text, style="FormLabel.TLabel")
        self.run_phase_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.run_phase_progress = ttk.Progressbar(
            progress_row,
            mode="determinate",
            length=360,
            maximum=100,
            variable=self.run_progress_value,
        )
        self.run_phase_progress.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(4, 0))
        self.request_progress_label.grid_remove()
        self.request_progress_bar.grid_remove()
        self.run_phase_label.grid_remove()
        self.run_phase_progress.grid_remove()

        output_frame = ttk.Frame(frame)
        output_frame.grid(row=12, column=0, columnspan=2, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self.results_notebook = ttk.Notebook(output_frame)
        self.results_notebook.grid(row=0, column=0, sticky="nsew")
        summary_tab = ttk.Frame(self.results_notebook, padding=(8, 8, 8, 8))
        rollup_tab = ttk.Frame(self.results_notebook, padding=(8, 8, 8, 8))
        sheets_tab = ttk.Frame(self.results_notebook, padding=(8, 8, 8, 8))
        json_tab = ttk.Frame(self.results_notebook)
        self.results_notebook.add(summary_tab, text="Estimator Summary")
        self.results_notebook.add(rollup_tab, text="Takeoff Rollup")
        self.results_notebook.add(sheets_tab, text="Sheet Navigator")
        self.results_notebook.add(json_tab, text="Raw JSON")

        summary_tab.columnconfigure(0, weight=1)
        summary_tab.rowconfigure(2, weight=1)
        summary_tab.rowconfigure(4, weight=1)
        ttk.Label(summary_tab, textvariable=self.summary_banner_text, style="FormLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        summary_actions = ttk.Frame(summary_tab)
        summary_actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(summary_actions, text="Export Takeoff CSV", command=self._export_takeoff_csv).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(summary_actions, text="Open Estimator Report", command=self._open_estimator_report).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(summary_actions, text="Show Reviewed Takeoff Lines", command=self._show_reviewed_takeoff_lines).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(
            summary_actions,
            text="Open Selected Line Source",
            command=self._open_selected_reviewed_line_source,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(summary_actions, text="Spec Compliance", command=self._show_spec_compliance_report).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Button(summary_actions, text="Export Handoff Package", command=self._export_handoff_package).grid(
            row=0, column=4, sticky="w", padx=(8, 0)
        )
        summary_table_frame = ttk.Frame(summary_tab)
        summary_table_frame.grid(row=2, column=0, sticky="nsew")
        summary_table_frame.columnconfigure(0, weight=1)
        summary_table_frame.rowconfigure(0, weight=1)
        self.summary_result_tree = ttk.Treeview(
            summary_table_frame,
            columns=("trade", "linear", "area", "volume", "counts", "status"),
            show="headings",
            height=10,
        )
        self.summary_result_tree.grid(row=0, column=0, sticky="nsew")
        for key, title, width, anchor in [
            ("trade", "Work Type", 180, "w"),
            ("linear", "Linear", 150, "e"),
            ("area", "Area", 150, "e"),
            ("volume", "Volume", 150, "e"),
            ("counts", "Counts", 180, "w"),
            ("status", "Review Status", 140, "w"),
        ]:
            self.summary_result_tree.heading(key, text=title)
            self.summary_result_tree.column(key, width=width, minwidth=80, stretch=True, anchor=anchor)
        summary_y_scroll = ttk.Scrollbar(
            summary_table_frame,
            orient="vertical",
            command=self.summary_result_tree.yview,
        )
        summary_y_scroll.grid(row=0, column=1, sticky="ns")
        summary_x_scroll = ttk.Scrollbar(
            summary_table_frame,
            orient="horizontal",
            command=self.summary_result_tree.xview,
        )
        summary_x_scroll.grid(row=1, column=0, sticky="ew")
        self.summary_result_tree.configure(
            yscrollcommand=summary_y_scroll.set,
            xscrollcommand=summary_x_scroll.set,
        )

        line_items_filter_frame = ttk.Frame(summary_tab)
        line_items_filter_frame.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        line_items_filter_frame.columnconfigure(0, weight=1)
        ttk.Label(
            line_items_filter_frame,
            textvariable=self.reviewed_line_items_banner_text,
            style="FormLabel.TLabel",
        ).grid(row=0, column=0, columnspan=7, sticky="w")
        ttk.Label(line_items_filter_frame, text="Work Type", style="FormLabel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 4), pady=(6, 0)
        )
        self.reviewed_line_items_filter_combo = ttk.Combobox(
            line_items_filter_frame,
            textvariable=self.reviewed_line_items_filter_trade,
            values=[_REVIEWED_LINE_ITEMS_ALL_FILTER],
            state="readonly",
            width=22,
        )
        self.reviewed_line_items_filter_combo.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.reviewed_line_items_filter_combo.bind(
            "<<ComboboxSelected>>",
            self._on_reviewed_line_item_filter_change,
        )
        ttk.Label(line_items_filter_frame, text="Item", style="FormLabel.TLabel").grid(
            row=1, column=2, sticky="w", padx=(10, 4), pady=(6, 0)
        )
        self.reviewed_line_items_item_filter_combo = ttk.Combobox(
            line_items_filter_frame,
            textvariable=self.reviewed_line_items_filter_item,
            values=[_REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER],
            state="readonly",
            width=22,
        )
        self.reviewed_line_items_item_filter_combo.grid(row=1, column=3, sticky="w", pady=(6, 0))
        self.reviewed_line_items_item_filter_combo.bind(
            "<<ComboboxSelected>>",
            self._on_reviewed_line_item_filter_change,
        )
        ttk.Button(
            line_items_filter_frame,
            text="Show All",
            command=self._clear_reviewed_line_item_filter,
        ).grid(row=1, column=4, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Button(
            line_items_filter_frame,
            text="Save Filtered CSV",
            command=self._save_filtered_reviewed_line_items_csv,
        ).grid(row=1, column=5, sticky="w", padx=(6, 0), pady=(6, 0))
        line_items_table_frame = ttk.Frame(summary_tab)
        line_items_table_frame.grid(row=4, column=0, sticky="nsew")
        line_items_table_frame.columnconfigure(0, weight=1)
        line_items_table_frame.rowconfigure(0, weight=1)
        self.reviewed_line_items_tree = ttk.Treeview(
            line_items_table_frame,
            columns=("trade", "item", "quantity", "unit", "description", "cost_code", "source"),
            show="headings",
            height=8,
        )
        self.reviewed_line_items_tree.grid(row=0, column=0, sticky="nsew")
        self.reviewed_line_items_tree.bind("<<TreeviewSelect>>", self._on_reviewed_line_item_select)
        self.reviewed_line_items_tree.bind("<Double-1>", self._open_selected_reviewed_line_source)
        for key, title, width, anchor in [
            ("trade", "Work Type", 130, "w"),
            ("item", "Measured Item", 150, "w"),
            ("quantity", "Qty", 90, "e"),
            ("unit", "Unit", 70, "w"),
            ("description", "Description", 260, "w"),
            ("cost_code", "Cost Code", 110, "w"),
            ("source", "Source", 160, "w"),
        ]:
            self.reviewed_line_items_tree.heading(key, text=title)
            self.reviewed_line_items_tree.column(key, width=width, minwidth=70, stretch=True, anchor=anchor)
        line_items_y_scroll = ttk.Scrollbar(
            line_items_table_frame,
            orient="vertical",
            command=self.reviewed_line_items_tree.yview,
        )
        line_items_y_scroll.grid(row=0, column=1, sticky="ns")
        line_items_x_scroll = ttk.Scrollbar(
            line_items_table_frame,
            orient="horizontal",
            command=self.reviewed_line_items_tree.xview,
        )
        line_items_x_scroll.grid(row=1, column=0, sticky="ew")
        self.reviewed_line_items_tree.configure(
            yscrollcommand=line_items_y_scroll.set,
            xscrollcommand=line_items_x_scroll.set,
        )

        rollup_tab.columnconfigure(0, weight=1)
        rollup_tab.rowconfigure(2, weight=1)
        ttk.Label(rollup_tab, textvariable=self.reviewed_rollup_banner_text, style="FormLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        rollup_actions = ttk.Frame(rollup_tab)
        rollup_actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(
            rollup_actions,
            text="Save Rollup CSV",
            command=self._save_reviewed_line_items_rollup_csv,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            rollup_actions,
            text="Show Selected Detail",
            command=self._show_selected_reviewed_rollup_detail,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        rollup_table_frame = ttk.Frame(rollup_tab)
        rollup_table_frame.grid(row=2, column=0, sticky="nsew")
        rollup_table_frame.columnconfigure(0, weight=1)
        rollup_table_frame.rowconfigure(0, weight=1)
        self.reviewed_line_items_rollup_tree = ttk.Treeview(
            rollup_table_frame,
            columns=("trade", "item", "quantity", "unit", "line_count", "cost_code", "source_sheets"),
            show="headings",
            height=14,
        )
        self.reviewed_line_items_rollup_tree.grid(row=0, column=0, sticky="nsew")
        self.reviewed_line_items_rollup_tree.bind("<<TreeviewSelect>>", self._on_reviewed_rollup_select)
        self.reviewed_line_items_rollup_tree.bind("<Double-1>", self._show_selected_reviewed_rollup_detail)
        for key, title, width, anchor in [
            ("trade", "Work Type", 150, "w"),
            ("item", "Measured Item", 180, "w"),
            ("quantity", "Total Qty", 100, "e"),
            ("unit", "Unit", 80, "w"),
            ("line_count", "Measurements", 110, "e"),
            ("cost_code", "Cost Code", 120, "w"),
            ("source_sheets", "Source Sheets", 260, "w"),
        ]:
            self.reviewed_line_items_rollup_tree.heading(key, text=title)
            self.reviewed_line_items_rollup_tree.column(key, width=width, minwidth=80, stretch=True, anchor=anchor)
        rollup_y_scroll = ttk.Scrollbar(
            rollup_table_frame,
            orient="vertical",
            command=self.reviewed_line_items_rollup_tree.yview,
        )
        rollup_y_scroll.grid(row=0, column=1, sticky="ns")
        rollup_x_scroll = ttk.Scrollbar(
            rollup_table_frame,
            orient="horizontal",
            command=self.reviewed_line_items_rollup_tree.xview,
        )
        rollup_x_scroll.grid(row=1, column=0, sticky="ew")
        self.reviewed_line_items_rollup_tree.configure(
            yscrollcommand=rollup_y_scroll.set,
            xscrollcommand=rollup_x_scroll.set,
        )

        sheets_tab.columnconfigure(0, weight=1)
        sheets_tab.rowconfigure(2, weight=1)
        ttk.Label(sheets_tab, textvariable=self.sheet_banner_text, style="FormLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        sheet_actions = ttk.Frame(sheets_tab)
        sheet_actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(sheet_actions, text="Show Review Queue", command=self._get_review_queue).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(sheet_actions, text="Refresh Current Job", command=self._refresh_job).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(sheet_actions, text="Open Linework View", command=self._open_visual_evidence_svg).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(sheet_actions, text="Measure Scale Visually", command=self._open_visual_measurement_page).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Button(
            sheet_actions,
            text="Preview Scale Calibration",
            command=self._show_scale_calibration_window,
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))
        sheet_table_frame = ttk.Frame(sheets_tab)
        sheet_table_frame.grid(row=2, column=0, sticky="nsew")
        sheet_table_frame.columnconfigure(0, weight=1)
        sheet_table_frame.rowconfigure(0, weight=1)
        self.sheet_navigator_tree = ttk.Treeview(
            sheet_table_frame,
            columns=("page", "sheet", "discipline", "type", "confidence", "flags"),
            show="headings",
            height=10,
            selectmode="browse",
        )
        self.sheet_navigator_tree.grid(row=0, column=0, sticky="nsew")
        for key, title, width, anchor in [
            ("page", "Page", 70, "e"),
            ("sheet", "Sheet ID", 180, "w"),
            ("discipline", "Work Type", 150, "w"),
            ("type", "View Type", 120, "w"),
            ("confidence", "Confidence", 90, "e"),
            ("flags", "Flags", 220, "w"),
        ]:
            self.sheet_navigator_tree.heading(key, text=title)
            self.sheet_navigator_tree.column(key, width=width, minwidth=60, stretch=True, anchor=anchor)
        self.sheet_navigator_tree.bind("<<TreeviewSelect>>", self._on_sheet_navigator_select)
        sheets_y_scroll = ttk.Scrollbar(
            sheet_table_frame,
            orient="vertical",
            command=self.sheet_navigator_tree.yview,
        )
        sheets_y_scroll.grid(row=0, column=1, sticky="ns")
        sheets_x_scroll = ttk.Scrollbar(
            sheet_table_frame,
            orient="horizontal",
            command=self.sheet_navigator_tree.xview,
        )
        sheets_x_scroll.grid(row=1, column=0, sticky="ew")
        self.sheet_navigator_tree.configure(
            yscrollcommand=sheets_y_scroll.set,
            xscrollcommand=sheets_x_scroll.set,
        )

        json_tab.columnconfigure(0, weight=1)
        json_tab.rowconfigure(1, weight=1)
        json_controls = ttk.Frame(json_tab, padding=(8, 6, 8, 4))
        json_controls.grid(row=0, column=0, columnspan=2, sticky="ew")
        json_controls.columnconfigure(2, weight=1)
        ttk.Button(
            json_controls,
            text="Show JSON Preview",
            command=self._show_json_preview,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            json_controls,
            text="Show Full JSON",
            command=self._show_full_json,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(
            json_controls,
            textvariable=self.json_view_status_text,
            style="FormLabel.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.output = Text(
            json_tab,
            wrap="none",
            background=p["field"],
            foreground=p["text"],
            insertbackground=p["cyan"],
            selectbackground=p["cyan"],
            selectforeground="#041016",
            padx=10,
            pady=10,
            font=("Cascadia Mono", 10),
        )
        self.output.grid(row=1, column=0, sticky="nsew")
        self.output_y_scroll = ttk.Scrollbar(json_tab, orient="vertical", command=self.output.yview)
        self.output_y_scroll.grid(row=1, column=1, sticky="ns")
        self.output_x_scroll = ttk.Scrollbar(json_tab, orient="horizontal", command=self.output.xview)
        self.output_x_scroll.grid(row=2, column=0, sticky="ew")
        self.output.configure(yscrollcommand=self.output_y_scroll.set, xscrollcommand=self.output_x_scroll.set)

        footer = ttk.Frame(frame)
        footer.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        footer.columnconfigure(1, weight=1)
        ttk.Separator(footer, orient="horizontal").grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        ttk.Label(footer, text="Ready", style="Footer.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(
            footer,
            text="F1 Help | Ctrl+O Open PDFs | Ctrl+Enter Submit",
            style="Footer.TLabel",
        ).grid(row=1, column=1, sticky="e")
        self.logo_label = Label(footer, background=p["surface"], borderwidth=0)
        self.logo_label.grid(row=1, column=2, sticky="e", padx=(12, 0))

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(12, weight=1)
        self._install_tooltips(
            frame=container,
            api_url_entry=api_url_entry,
            api_key_entry=api_key_entry,
            tenant_id_entry=tenant_id_entry,
            selected_trades_entry=selected_trades_entry,
            overrides_entry=overrides_entry,
            current_job_entry=current_job_entry,
            notes_entry=notes_entry,
            prune_statuses_entry=prune_statuses_entry,
            prune_older_than_entry=prune_older_than_entry,
            prune_limit_entry=prune_limit_entry,
        )
        self._refresh_guided_flow()
        self._refresh_trade_selection_hint()
        self._apply_advanced_tools_visibility(update_status=False)
        self._install_company_logo()
        self._apply_visual_theme(update_status=False)
        self._set_inline_setup_visibility(False)

    def _set_inline_setup_visibility(self, visible: bool) -> None:
        for widget in self._inline_setup_widgets:
            try:
                if visible:
                    widget.grid()
                else:
                    widget.grid_remove()
            except Exception:
                continue

    def _close_setup_window(self) -> None:
        if self.setup_window is not None:
            try:
                self.setup_window.destroy()
            except Exception:
                pass
        self.setup_window = None
        self.setup_scroll_canvas = None
        self.setup_project_combo = None
        self._setup_window_is_open = False

    def _refresh_project_selector(self) -> None:
        names = sorted(self.project_profiles.keys(), key=lambda value: value.casefold())
        active_name = self.active_project_name.get().strip()

        if self.project_selector_combo is not None:
            self.project_selector_combo.configure(values=names)
        if self.setup_project_combo is not None:
            self.setup_project_combo.configure(values=names)

        if active_name and active_name in self.project_profiles:
            return
        if names:
            self.active_project_name.set(names[0])
            if not self.project_setup_name.get().strip():
                self.project_setup_name.set(names[0])
            return
        self.active_project_name.set("")
        if not self.project_setup_name.get().strip():
            self.project_setup_name.set("")

    def _normalize_project_payload(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            payload = {}

        def _as_bool(value: object, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                token = value.strip().lower()
                if token in {"1", "true", "yes", "on"}:
                    return True
                if token in {"0", "false", "no", "off"}:
                    return False
            return default

        analysis_mode = str(payload.get("analysis_mode", self.analysis_mode.get())).strip()
        if analysis_mode not in {"auto", "selected", "all"}:
            analysis_mode = self.analysis_mode.get().strip() or "all"

        current_job_id = str(payload.get("current_job_id", "")).strip()

        guided_step = str(payload.get("guided_step", self.guided_step.get())).strip()
        if guided_step not in {"trade", "run"}:
            guided_step = "trade"

        guided_trade_strategy = str(
            payload.get("guided_trade_strategy", self.guided_trade_strategy.get())
        ).strip()
        if guided_trade_strategy not in {"auto", "selected", "all"}:
            guided_trade_strategy = analysis_mode

        guided_run_objective = str(
            payload.get("guided_run_objective", self.guided_run_objective.get())
        ).strip()
        if guided_run_objective not in {
            "takeoff_and_estimation",
            "takeoff_only",
            "manhours_only",
        }:
            guided_run_objective = "takeoff_and_estimation"

        theme_preset = str(payload.get("theme_preset", self.theme_preset.get())).strip()
        if theme_preset not in _THEME_PRESETS:
            theme_preset = _DEFAULT_THEME_PRESET

        files_value = payload.get("files", [])
        files: list[str] = []
        if isinstance(files_value, list):
            for item in files_value:
                token = str(item).strip()
                if token:
                    files.append(token)

        return {
            "api_url": str(payload.get("api_url", self.api_url.get())).strip(),
            "tenant_id": str(payload.get("tenant_id", self.tenant_id.get())).strip() or "default",
            "analysis_mode": analysis_mode,
            "selected_trades": str(payload.get("selected_trades", "")).strip(),
            "sheet_overrides_path": str(payload.get("sheet_overrides_path", "")).strip(),
            "spec_profile_ids": str(payload.get("spec_profile_ids", "")).strip(),
            "spec_organization": str(payload.get("spec_organization", "")).strip(),
            "current_job_id": current_job_id,
            "include_public_specs": _as_bool(
                payload.get("include_public_specs"),
                bool(self.include_public_specs.get()),
            ),
            "publish_uploaded_specs": _as_bool(
                payload.get("publish_uploaded_specs"),
                bool(self.publish_uploaded_specs.get()),
            ),
            "notes": str(payload.get("notes", "")),
            "files": files,
            "include_all_template": _as_bool(
                payload.get("include_all_template"),
                bool(self.include_all_template.get()),
            ),
            "include_unmapped_benchmark": _as_bool(
                payload.get("include_unmapped_benchmark"),
                bool(self.include_unmapped_benchmark.get()),
            ),
            "guided_step": guided_step,
            "guided_trade_strategy": guided_trade_strategy,
            "guided_run_objective": guided_run_objective,
            "theme_preset": theme_preset,
            "dark_mode_enabled": _as_bool(
                payload.get("dark_mode_enabled"),
                bool(self.dark_mode_enabled.get()),
            ),
            "banner_animation_enabled": _as_bool(
                payload.get("banner_animation_enabled"),
                bool(self.banner_animation_enabled.get()),
            ),
        }

    def _project_payload_from_current(self) -> dict[str, object]:
        payload = {
            "api_url": self.api_url.get().strip(),
            "tenant_id": self.tenant_id.get().strip() or "default",
            "analysis_mode": self.analysis_mode.get().strip(),
            "selected_trades": self.selected_trades.get().strip(),
            "sheet_overrides_path": self.sheet_overrides_path.get().strip(),
            "spec_profile_ids": self.spec_profile_ids.get().strip(),
            "spec_organization": self.spec_organization.get().strip(),
            "current_job_id": self.current_job_id.get().strip(),
            "include_public_specs": bool(self.include_public_specs.get()),
            "publish_uploaded_specs": bool(self.publish_uploaded_specs.get()),
            "notes": self.notes.get(),
            "files": [str(path).strip() for path in self.files if str(path).strip()],
            "include_all_template": bool(self.include_all_template.get()),
            "include_unmapped_benchmark": bool(self.include_unmapped_benchmark.get()),
            "guided_step": self.guided_step.get().strip(),
            "guided_trade_strategy": self.guided_trade_strategy.get().strip(),
            "guided_run_objective": self.guided_run_objective.get().strip(),
            "theme_preset": self.theme_preset.get().strip(),
            "dark_mode_enabled": bool(self.dark_mode_enabled.get()),
            "banner_animation_enabled": bool(self.banner_animation_enabled.get()),
        }
        return self._normalize_project_payload(payload)

    def _apply_project_payload(self, payload: object, *, project_name: str) -> None:
        normalized = self._normalize_project_payload(payload)
        self.api_url.set(str(normalized.get("api_url", "")).strip() or "http://127.0.0.1:8000")
        self.tenant_id.set(str(normalized.get("tenant_id", "default")).strip() or "default")
        self.analysis_mode.set(str(normalized.get("analysis_mode", "all")).strip())
        self.selected_trades.set(str(normalized.get("selected_trades", "")).strip())
        self.sheet_overrides_path.set(str(normalized.get("sheet_overrides_path", "")).strip())
        self.spec_profile_ids.set(str(normalized.get("spec_profile_ids", "")).strip())
        self.spec_organization.set(str(normalized.get("spec_organization", "")).strip())
        self.current_job_id.set(str(normalized.get("current_job_id", "")).strip())
        self.include_public_specs.set(bool(normalized.get("include_public_specs", True)))
        self.publish_uploaded_specs.set(bool(normalized.get("publish_uploaded_specs", False)))
        self.notes.set(str(normalized.get("notes", "")))
        self.include_all_template.set(bool(normalized.get("include_all_template", False)))
        self.include_unmapped_benchmark.set(bool(normalized.get("include_unmapped_benchmark", True)))
        self.guided_step.set(str(normalized.get("guided_step", "trade")).strip())
        self.guided_trade_strategy.set(
            str(normalized.get("guided_trade_strategy", self.analysis_mode.get().strip())).strip()
        )
        self.guided_run_objective.set(
            str(normalized.get("guided_run_objective", "takeoff_and_estimation")).strip()
        )
        self.theme_preset.set(str(normalized.get("theme_preset", _DEFAULT_THEME_PRESET)).strip())
        self.dark_mode_enabled.set(bool(normalized.get("dark_mode_enabled", True)))
        self.banner_animation_enabled.set(bool(normalized.get("banner_animation_enabled", True)))

        files_value = normalized.get("files", [])
        restored_files: list[str] = []
        if isinstance(files_value, list):
            for item in files_value:
                token = str(item).strip()
                if token:
                    restored_files.append(token)
        self.files = restored_files
        self._file_scan_meta = {}
        self._file_scan_token += 1
        self._refresh_files_label()
        if self.files:
            self._start_selected_file_scan(self.files)

        self.active_project_name.set(project_name)
        self.project_setup_name.set(project_name)
        self._refresh_project_selector()
        self._save_settings()

    def _load_project_profiles(self) -> None:
        profiles: dict[str, dict[str, object]] = {}
        active_name = ""

        if self.projects_store_path.exists():
            try:
                loaded = json.loads(self.projects_store_path.read_text(encoding="utf-8"))
            except Exception as exc:
                self.runtime_logger.warn(f"Project profile load failed ({self.projects_store_path}): {exc}")
                self.status_text.set(
                    f"Could not read saved project profiles. Using defaults. ({self.projects_store_path.name})"
                )
                loaded = {}
            if isinstance(loaded, dict):
                active_name = str(loaded.get("active_project_name", "")).strip()
                loaded_profiles = loaded.get("projects", {})
                if isinstance(loaded_profiles, dict):
                    for raw_name, payload in loaded_profiles.items():
                        name = str(raw_name).strip()
                        if not name:
                            continue
                        profiles[name] = self._normalize_project_payload(payload)

        self.project_profiles = profiles
        if active_name and active_name in self.project_profiles:
            self.active_project_name.set(active_name)
            if not self.project_setup_name.get().strip():
                self.project_setup_name.set(active_name)
        self._refresh_project_selector()

    def _save_project_profiles(self) -> None:
        payload = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "active_project_name": self.active_project_name.get().strip(),
            "projects": self.project_profiles,
        }
        try:
            self.projects_store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self.runtime_logger.warn(f"Project profile save failed ({self.projects_store_path}): {exc}")
            self.status_text.set(
                f"Could not save project profiles. Check file permissions: {self.projects_store_path.name}"
            )
            return

    def _save_project_profile_from_current(self) -> None:
        name = self.project_setup_name.get().strip() or self.active_project_name.get().strip()
        if not name:
            if self.files:
                name = Path(self.files[0]).stem.strip()
            if not name:
                name = f"Project-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        name = re.sub(r"\s+", " ", name).strip()[:80]
        if not name:
            name = f"Project-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        self.project_profiles[name] = self._project_payload_from_current()
        self.active_project_name.set(name)
        self.project_setup_name.set(name)
        self._refresh_project_selector()
        self._save_project_profiles()
        self._save_settings()
        self.status_text.set(f"Saved project profile: {name}")

    def _load_selected_project_profile_event(self, _event: object = None) -> None:
        self._load_selected_project_profile()

    def _load_selected_project_profile(self) -> None:
        name = self.active_project_name.get().strip()
        if not name:
            if self.project_profiles:
                first = sorted(self.project_profiles.keys(), key=lambda value: value.casefold())[0]
                self.active_project_name.set(first)
                name = first
            else:
                self.status_text.set("No saved projects found yet. Save a project snapshot first.")
                return
        payload = self.project_profiles.get(name)
        if payload is None:
            self.status_text.set(f"Project profile not found: {name}")
            return
        self._apply_project_payload(payload, project_name=name)
        job_id = self.current_job_id.get().strip()
        job_text = f" with saved job {job_id[:12]}..." if job_id else ""
        self.status_text.set(f"Loaded project profile: {name}{job_text}")

    def _open_saved_project_job(self) -> None:
        self._load_selected_project_profile()
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text(
                "This saved project does not have a job number yet.\n"
                "Start a background takeoff first, then save the project snapshot again."
            )
            self.status_text.set("Saved project has no job number.")
            return
        self._refresh_job()

    def _autosave_active_project_snapshot(self) -> None:
        name = self.active_project_name.get().strip() or self.project_setup_name.get().strip()
        if not name:
            if self.files:
                name = Path(self.files[0]).stem.strip()
            elif self.current_job_id.get().strip():
                name = f"Job-{self.current_job_id.get().strip()[:8]}"
            else:
                return
        name = re.sub(r"\s+", " ", name).strip()[:80]
        if not name:
            return
        self.project_profiles[name] = self._project_payload_from_current()
        self.active_project_name.set(name)
        self.project_setup_name.set(name)
        self._refresh_project_selector()
        self._save_project_profiles()

    def _start_new_project_profile(self) -> None:
        default_name = f"Project-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.active_project_name.set("")
        self.project_setup_name.set(default_name)
        self.current_job_id.set("")
        self.notes.set("")
        self.selected_trades.set("")
        self.sheet_overrides_path.set("")
        self.spec_profile_ids.set("")
        self.spec_organization.set("NASA")
        self.include_public_specs.set(True)
        self.publish_uploaded_specs.set(False)
        self.files = []
        self._file_scan_meta = {}
        self._file_scan_token += 1
        self._refresh_files_label()
        self._save_settings()
        self.status_text.set(
            "New project started. Pick drawing files, then click Save Project Snapshot."
        )

    def _open_project_setup_window(self) -> None:
        if self.setup_window is not None and self._setup_window_is_open:
            try:
                self.setup_window.deiconify()
                self.setup_window.lift()
                self.setup_window.focus_force()
                return
            except Exception:
                self._close_setup_window()

        self._set_inline_setup_visibility(False)

        setup = Toplevel(self.root)
        self.setup_window = setup
        self._setup_window_is_open = True
        setup.title("EstimateForge Project Setup")
        setup.geometry("1120x720")
        setup.minsize(1000, 620)
        setup.configure(background=_THEME["surface"])
        setup.protocol("WM_DELETE_WINDOW", self._close_setup_window)

        self.setup_scroll_canvas, container = self._build_scrollable_surface(
            parent=setup,
            container_style="Panel.TFrame",
            padding=(18, 16, 18, 16),
            canvas_background=_THEME["surface"],
            min_width=1000,
            min_height=620,
        )
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="EstimateForge Project Setup", style="HeaderTitle.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        ttk.Label(
            container,
            text=(
                "Use this screen to pick drawings, set trade scope, and save reusable project profiles. "
                "After your first run, create a sheet-fix file, edit it, and rerun to train better sheet IDs."
            ),
            style="HeaderSub.TLabel",
            wraplength=960,
            justify="left",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 12))

        ttk.Label(container, text="Project Name", style="FormLabel.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Entry(container, textvariable=self.project_setup_name, width=52).grid(
            row=2, column=1, sticky="ew"
        )
        ttk.Button(
            container,
            text="Save Project Snapshot",
            command=self._save_project_profile_from_current,
            style="Accent.TButton",
        ).grid(row=2, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            container,
            text="New Project",
            command=self._start_new_project_profile,
        ).grid(row=2, column=3, sticky="w", padx=(8, 0))

        ttk.Label(container, text="Saved Projects", style="FormLabel.TLabel").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.setup_project_combo = ttk.Combobox(
            container,
            textvariable=self.active_project_name,
            state="readonly",
            width=52,
            values=[],
        )
        self.setup_project_combo.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        self.setup_project_combo.bind(
            "<<ComboboxSelected>>",
            self._load_selected_project_profile_event,
        )
        ttk.Button(
            container,
            text="Load Saved Project",
            command=self._load_selected_project_profile,
        ).grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Button(
            container,
            text="Open Saved Job",
            command=self._open_saved_project_job,
            style="Accent.TButton",
        ).grid(row=3, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        self._refresh_project_selector()

        ttk.Separator(container, orient="horizontal").grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=(12, 10)
        )

        ttk.Label(container, text="Step 1: Drawings", style="Section.TLabel").grid(
            row=5, column=0, sticky="w"
        )
        drawings_row = ttk.Frame(container)
        drawings_row.grid(row=5, column=1, columnspan=3, sticky="ew")
        drawings_row.columnconfigure(1, weight=1)
        ttk.Button(
            drawings_row,
            text="Pick Drawing Files",
            command=self._choose_pdfs,
            style="Primary.TButton",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(drawings_row, textvariable=self.header_files_text, style="SummaryChip.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        ttk.Label(container, text="Step 2: Work Types", style="Section.TLabel").grid(
            row=6, column=0, sticky="w", pady=(10, 0)
        )
        scope_row = ttk.Frame(container)
        scope_row.grid(row=6, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Combobox(
            scope_row,
            textvariable=self.analysis_mode,
            state="readonly",
            width=22,
            values=self.analysis_mode_catalog,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            scope_row,
            text="Find Work Types from Drawings",
            command=self._discover_trade_options_from_drawings,
            style="Accent.TButton",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            scope_row,
            text="Load Work Types",
            command=self._load_trade_catalog,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            scope_row,
            text="Check Work Types",
            command=self._validate_selected_trades_clicked,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(container, text="Chosen Work Types", style="FormLabel.TLabel").grid(
            row=7, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(
            container,
            textvariable=self.selected_trades,
            state="readonly",
            width=80,
        ).grid(row=7, column=1, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Label(container, text="Step 3: Sheet Names (optional)", style="Section.TLabel").grid(
            row=8, column=0, sticky="w", pady=(10, 0)
        )
        fix_row = ttk.Frame(container)
        fix_row.grid(row=8, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        fix_row.columnconfigure(0, weight=1)
        ttk.Entry(
            fix_row,
            textvariable=self.sheet_overrides_path,
            width=84,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            fix_row,
            text="Pick Sheet Fix File",
            command=self._choose_overrides_file,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            fix_row,
            text="Create Sheet Name Review File",
            command=self._export_overrides_template,
            style="Accent.TButton",
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(container, text="Step 4: Standards and Specs", style="Section.TLabel").grid(
            row=9, column=0, sticky="w", pady=(10, 0)
        )
        specs_row = ttk.Frame(container)
        specs_row.grid(row=9, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(specs_row, text="Agency / Company").grid(row=0, column=0, sticky="w")
        self.spec_org_combo = ttk.Combobox(
            specs_row,
            textvariable=self.spec_organization,
            state="normal",
            width=30,
            values=[],
        )
        self.spec_org_combo.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Checkbutton(
            specs_row,
            text="Use Public Specs for Selected Agency",
            variable=self.include_public_specs,
        ).grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Button(
            specs_row,
            text="Load Agencies",
            command=self._refresh_spec_organizations,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Button(
            specs_row,
            text="Load Matching Specs",
            command=self._load_spec_catalog_for_org,
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Checkbutton(
            specs_row,
            text="Share Uploaded Spec Files Publicly",
            variable=self.publish_uploaded_specs,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(container, text="Selected Specs", style="FormLabel.TLabel").grid(
            row=10, column=0, sticky="w", pady=(8, 0)
        )
        spec_ids_row = ttk.Frame(container)
        spec_ids_row.grid(row=10, column=1, columnspan=3, sticky="ew", pady=(8, 0))
        spec_ids_row.columnconfigure(0, weight=1)
        ttk.Entry(spec_ids_row, textvariable=self.spec_profile_ids, width=84).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(
            spec_ids_row,
            text="Upload Spec File",
            command=self._upload_spec_file,
            style="Accent.TButton",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            spec_ids_row,
            text="Find Compliant Submittal Links",
            command=self._search_spec_submittals,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(container, text="Project Notes", style="FormLabel.TLabel").grid(
            row=11, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Entry(container, textvariable=self.notes, width=84).grid(
            row=11, column=1, columnspan=3, sticky="ew", pady=(10, 0)
        )

        ttk.Label(container, text="Step 5: Run", style="Section.TLabel").grid(
            row=12, column=0, sticky="w", pady=(12, 0)
        )
        run_row = ttk.Frame(container)
        run_row.grid(row=12, column=1, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(
            run_row,
            text="Start Background Takeoff",
            command=self._submit_async_job,
            style="Primary.TButton",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            run_row,
            text="Run Takeoff Now",
            command=self._run_analysis,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            run_row,
            text="Check Takeoff Status",
            command=self._refresh_job,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            run_row,
            text="Use Newest Job",
            command=self._load_latest_job,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        training_row = ttk.Frame(container)
        training_row.grid(row=13, column=1, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Button(
            training_row,
            text="Run Job Again with Current Fix File",
            command=self._rerun_job,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            training_row,
            text="Show Sheets to Review",
            command=self._get_review_queue,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            training_row,
            text="Close Setup Window",
            command=self._close_setup_window,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(
            container,
            text=(
                "Tip: First run with no sheet fix file. Then click 'Create Sheet Fix File from Last Run', "
                "edit that JSON, pick it above, and rerun. Those corrections become reusable project knowledge."
            ),
            wraplength=980,
            justify="left",
            style="HeaderSub.TLabel",
        ).grid(row=14, column=0, columnspan=4, sticky="w", pady=(14, 0))

        self._refresh_spec_organizations()

    def _draw_construction_banner(self, banner: Canvas | None) -> None:
        if banner is None:
            return
        p = _THEME
        width = max(1, int(banner.winfo_width()))
        height = max(1, int(banner.winfo_height()))
        phase = self._banner_phase
        banner.delete("all")

        banner.create_rectangle(0, 0, width, height, fill=p["app_bg"], outline="")
        for x in range(0, width, 28):
            fill = "#071018" if (x // 28) % 2 == 0 else "#0A121A"
            banner.create_rectangle(x, 0, x + 28, height, fill=fill, outline="")

        grid_offset = -((phase * 2) % 48)
        for x in range(grid_offset, width, 48):
            banner.create_line(x, 0, x, height, fill="#102B36", width=1)
        for y in range(10, height, 22):
            banner.create_line(0, y, width, y, fill="#0C222E", width=1)

        beam_x = ((phase * 8) % (width + 180)) - 90
        banner.create_rectangle(beam_x - 46, 0, beam_x + 46, height, fill=p["cyan"], stipple="gray75", outline="")
        banner.create_line(beam_x, 0, beam_x, height, fill=p["lime"], width=2)

        rail_y = height - 16
        banner.create_rectangle(0, rail_y, width, height, fill="#100D08", outline="")
        for offset in range(-44 + ((phase * 3) % 44), width + 44, 44):
            banner.create_polygon(
                offset,
                rail_y,
                offset + 18,
                rail_y,
                offset + 44,
                height,
                offset + 26,
                height,
                fill=p["amber"],
                outline="",
            )

        center_y = (height // 2) - 2
        icon_x = 34
        banner.create_polygon(
            icon_x,
            center_y - 24,
            icon_x + 40,
            center_y - 24,
            icon_x + 58,
            center_y,
            icon_x + 40,
            center_y + 24,
            icon_x,
            center_y + 24,
            icon_x - 18,
            center_y,
            fill="#06131A",
            outline=p["cyan"],
            width=2,
        )
        for level in range(3):
            y = center_y + 13 - (level * 12)
            banner.create_line(icon_x + 2, y, icon_x + 34, y, fill=p["cyan_dim"], width=2)
        banner.create_line(icon_x + 43, center_y - 16, icon_x + 43, center_y + 14, fill=p["amber"], width=2)
        banner.create_arc(
            icon_x + 33,
            center_y + 6,
            icon_x + 53,
            center_y + 26,
            start=210,
            extent=270,
            style="arc",
            outline=p["amber"],
            width=2,
        )

        banner.create_text(
            104,
            center_y - 10,
            anchor="w",
            fill=p["text"],
            text="AI ESTIMATING COMMAND CENTER",
            font=("Segoe UI Semibold", 15),
        )
        banner.create_text(
            106,
            center_y + 12,
            anchor="w",
            fill=p["muted"],
            text="PDFS -> TAKEOFF -> SCOPE -> PRICE -> HANDOFF",
            font=("Segoe UI Semibold", 9),
        )

        graph_start = 470
        graph_end = max(graph_start + 60, width - 350)
        if graph_end > graph_start:
            points: list[float] = []
            for x in range(graph_start, graph_end, 14):
                wave = math.sin((x + (phase * 10)) / 38.0) * 7
                points.extend([float(x), float(center_y + wave)])
            if len(points) >= 4:
                banner.create_line(*points, fill=p["lime"], width=2, smooth=True)
            for x in range(graph_start, graph_end, 84):
                wave = math.sin((x + (phase * 10)) / 38.0) * 7
                y = center_y + wave
                banner.create_oval(x - 4, y - 4, x + 4, y + 4, fill=p["magenta"], outline="")

        if width > 980:
            panel_x = width - 318
            banner.create_rectangle(panel_x, 12, width - 22, height - 22, fill="#071018", outline=p["cyan_dim"], width=1)
            banner.create_text(
                panel_x + 16,
                28,
                anchor="w",
                fill=p["cyan"],
                text="LIVE ESTIMATE INTELLIGENCE",
                font=("Segoe UI Semibold", 9),
            )
            banner.create_text(
                panel_x + 16,
                48,
                anchor="w",
                fill=p["text"],
                text="Scope validation | Job status | Benchmark signal",
                font=("Segoe UI", 8),
            )
            pulse = 6 + int((math.sin(phase / 3.0) + 1) * 3)
            banner.create_oval(width - 48 - pulse, 25 - pulse, width - 48 + pulse, 25 + pulse, outline=p["lime"], width=2)
            banner.create_oval(width - 52, 21, width - 44, 29, fill=p["lime"], outline="")

        banner.create_rectangle(0, 0, width - 1, height - 1, outline=p["cyan"], width=2)

    def _start_banner_animation(self) -> None:
        if not bool(self.banner_animation_enabled.get()):
            self._draw_construction_banner(self.construction_banner)
            return
        if self._banner_after_id is not None:
            return
        self._animate_construction_banner()

    def _animate_construction_banner(self) -> None:
        if not bool(self.banner_animation_enabled.get()):
            self._banner_after_id = None
            self._draw_construction_banner(self.construction_banner)
            return
        if self.construction_banner is None:
            self._banner_after_id = None
            return
        self._banner_phase = (self._banner_phase + 1) % 10000
        self._draw_construction_banner(self.construction_banner)
        self._banner_after_id = self.root.after(90, self._animate_construction_banner)

    def _toggle_banner_animation(self, *, update_status: bool = True) -> None:
        enabled = bool(self.banner_animation_enabled.get())
        if enabled:
            self._start_banner_animation()
        else:
            if self._banner_after_id is not None:
                try:
                    self.root.after_cancel(self._banner_after_id)
                except Exception:
                    pass
                self._banner_after_id = None
            self._draw_construction_banner(self.construction_banner)
        if update_status:
            self.status_text.set(
                "Banner animation enabled." if enabled else "Banner animation paused."
            )
            self._save_settings()

    def _bind_mousewheel_scrollable_canvas(self, canvas: Canvas) -> None:
        def _on_mousewheel(event: object) -> None:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                num = int(getattr(event, "num", 0))
                if num == 4:
                    canvas.yview_scroll(-1, "units")
                elif num == 5:
                    canvas.yview_scroll(1, "units")
                return
            canvas.yview_scroll(int(-delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        canvas.bind("<Button-4>", _on_mousewheel)
        canvas.bind("<Button-5>", _on_mousewheel)

    def _install_tooltips(
        self,
        *,
        frame: ttk.Frame,
        api_url_entry: ttk.Entry,
        api_key_entry: ttk.Entry,
        tenant_id_entry: ttk.Entry,
        selected_trades_entry: ttk.Entry,
        overrides_entry: ttk.Entry,
        current_job_entry: ttk.Entry,
        notes_entry: ttk.Entry,
        prune_statuses_entry: ttk.Entry,
        prune_older_than_entry: ttk.Entry,
        prune_limit_entry: ttk.Entry,
    ) -> None:
        self._control_specs = self._control_specs_for_ui()
        self._control_widgets = {}
        self._control_tooltips = {}
        pro_label_to_key = {
            spec["pro_label"]: key for key, spec in self._control_specs.items()
        }
        for widget in self._walk_widgets(frame):
            class_name = ""
            try:
                class_name = str(widget.winfo_class())
            except Exception:
                continue
            if class_name not in {"TButton", "TCheckbutton"}:
                continue
            try:
                text = str(widget.cget("text"))
            except Exception:
                continue
            key = pro_label_to_key.get(text)
            if not key:
                continue
            spec = self._control_specs.get(key)
            if not spec:
                continue
            self._control_widgets[key] = widget
            tooltip = self._add_tooltip(widget, spec["pro_tip"])
            if tooltip:
                self._control_tooltips[key] = tooltip

        self._field_tooltip_specs = {
            "api_url": {
                "pro_tip": "Base API endpoint. Use local default unless pointing to a remote service.",
                "beginner_tip": "Where this app sends requests. Leave this as the local address unless told otherwise.",
            },
            "api_key": {
                "pro_tip": (
                    "Optional API key sent as x-api-key. Required only when remote service enforces auth."
                ),
                "beginner_tip": (
                    "Optional security key. Leave empty for local server; use one for protected remote servers."
                ),
            },
            "tenant_id": {
                "pro_tip": "Tenant/company scope sent as x-tenant-id for job isolation and access boundaries.",
                "beginner_tip": "Company workspace ID. Keep this consistent so jobs stay grouped to your company.",
            },
            "analysis_mode": {
                "pro_tip": "auto=detect trades from drawings, selected=only selected trades, all=analyze all supported trades.",
                "beginner_tip": "Trade Selection Settings: auto analyzes drawings to pick trades, selected uses your trade list, all runs every trade.",
            },
            "selected_trades": {
                "pro_tip": "Selected trade tokens generated from checkbox options when Analysis Mode is selected.",
                "beginner_tip": "Use the work-type checkboxes below. This line fills in automatically.",
            },
            "overrides_path": {
                "pro_tip": "Path to JSON that overrides inferred sheet IDs and titles.",
                "beginner_tip": "Optional fix file for sheet names if auto-detection is wrong.",
            },
            "current_job": {
                "pro_tip": "Target job ID for refresh, rerun, cancel, and review workflows.",
                "beginner_tip": "Job number used to check status, rerun, or stop a background run.",
            },
            "notes": {
                "pro_tip": "Optional run context or assumptions saved with the request.",
                "beginner_tip": "Optional notes for this run (scope, clarifications, assumptions).",
            },
            "prune_statuses": {
                "pro_tip": "Comma-separated terminal statuses to prune (completed, failed, canceled).",
                "beginner_tip": "Which finished job types can be cleaned up.",
            },
            "prune_older_than": {
                "pro_tip": "Only prune jobs older than this many hours.",
                "beginner_tip": "Only clean jobs older than this number of hours.",
            },
            "prune_limit": {
                "pro_tip": "Maximum number of jobs to evaluate/prune in one operation.",
                "beginner_tip": "Maximum jobs to check in one cleanup run.",
            },
            "output_panel": {
                "pro_tip": "Output panel for API responses, reports, and run diagnostics.",
                "beginner_tip": "Main results window. Job results and messages appear here.",
            },
        }
        self._field_tooltips = {}
        self._field_label_specs = self._field_label_specs_for_ui()
        self._field_label_tooltips = {}
        field_widgets: dict[str, object] = {
            "api_url": api_url_entry,
            "api_key": api_key_entry,
            "tenant_id": tenant_id_entry,
            "analysis_mode": self.analysis_mode_combo,
            "selected_trades": selected_trades_entry,
            "overrides_path": overrides_entry,
            "current_job": current_job_entry,
            "notes": notes_entry,
            "prune_statuses": prune_statuses_entry,
            "prune_older_than": prune_older_than_entry,
            "prune_limit": prune_limit_entry,
            "output_panel": self.output,
        }
        for key, widget in field_widgets.items():
            spec = self._field_tooltip_specs.get(key)
            if not spec:
                continue
            tooltip = self._add_tooltip(widget, spec["pro_tip"])
            if tooltip:
                self._field_tooltips[key] = tooltip

        for key, widget in self._field_label_widgets.items():
            spec = self._field_label_specs.get(key)
            if not spec:
                continue
            tooltip = self._add_tooltip(widget, spec["pro_tip"])
            if tooltip:
                self._field_label_tooltips[key] = tooltip

        self._apply_beginner_mode(update_status=False)

    def _control_specs_for_ui(self) -> dict[str, dict[str, str]]:
        return {
            "start_local_api": {
                "pro_label": "Start Local API",
                "beginner_label": "Start Local Server",
                "pro_tip": "Start the local backend service at the API URL if it is not already running.",
                "beginner_tip": "Turn on the local engine so this app can run jobs.",
            },
            "restart_api": {
                "pro_label": "Restart API",
                "beginner_label": "Restart Server",
                "pro_tip": "Stop and immediately restart the local backend process managed by this desktop app.",
                "beginner_tip": "Restart the local server now if it is acting up.",
            },
            "shutdown_api": {
                "pro_label": "Shutdown API",
                "beginner_label": "Stop Server",
                "pro_tip": "Stop the local backend process started by this desktop app.",
                "beginner_tip": "Turn off the local server this app started.",
            },
            "check_api_health": {
                "pro_label": "Check API Health",
                "beginner_label": "Check Server Details",
                "pro_tip": "Call the API health endpoint and show status, version, process ID, start time, and database path.",
                "beginner_tip": "Show which local server is running and whether it may need a restart.",
            },
            "load_saved_project": {
                "pro_label": "Load Saved Project",
                "beginner_label": "Load Project",
                "pro_tip": "Restore the selected project profile: files, settings, specs, sheet fix file, and saved job ID.",
                "beginner_tip": "Open a saved project setup without browsing for files again.",
            },
            "open_saved_job": {
                "pro_label": "Open Saved Job",
                "beginner_label": "Open Project Results",
                "pro_tip": "Load the selected project profile and fetch the saved job result/status from the API.",
                "beginner_tip": "Open the saved takeoff result for this project.",
            },
            "save_project_snapshot": {
                "pro_label": "Save Project Snapshot",
                "beginner_label": "Save Project",
                "pro_tip": "Save current project files, settings, specs, sheet fix file, and job ID to the local project library.",
                "beginner_tip": "Save this project so it can be opened again later.",
            },
            "project_setup_window": {
                "pro_label": "Project Setup Window",
                "beginner_label": "Project Setup",
                "pro_tip": "Open the guided project setup workspace with drawings, specs, sheet fix file, and run controls.",
                "beginner_tip": "Open the project setup screen.",
            },
            "new_project": {
                "pro_label": "New Project",
                "beginner_label": "Start New Project",
                "pro_tip": "Clear current project files and run fields so a new estimate can be started.",
                "beginner_tip": "Clear the current project and start a new one.",
            },
            "quick_path_load": {
                "pro_label": "1) Load Drawings",
                "beginner_label": "1) Load Drawings",
                "pro_tip": "Step 1 in the estimator flow: pick one or more drawing PDFs.",
                "beginner_tip": "Start here: choose your drawing files.",
            },
            "quick_path_confirm": {
                "pro_label": "2) Confirm Work Types",
                "beginner_label": "2) Confirm Work Types",
                "pro_tip": "Step 2 in the estimator flow: scan drawings and confirm available work types.",
                "beginner_tip": "Check which work types should be included.",
            },
            "quick_path_run": {
                "pro_label": "3) Run Takeoff",
                "beginner_label": "3) Run Takeoff",
                "pro_tip": "Step 3 in the estimator flow: run takeoff and estimation workflow.",
                "beginner_tip": "Run the estimate after drawings and work types are ready.",
            },
            "guided_back": {
                "pro_label": "Guided Back",
                "beginner_label": "Go Back",
                "pro_tip": "Return to the previous guided setup step.",
                "beginner_tip": "Go back to the previous guided question.",
            },
            "guided_proceed": {
                "pro_label": "Guided Proceed",
                "beginner_label": "Proceed",
                "pro_tip": "Advance to the next guided step based on selected trade strategy.",
                "beginner_tip": "Move to the next step.",
            },
            "guided_execute": {
                "pro_label": "Run Guided Step",
                "beginner_label": "Proceed with Analysis",
                "pro_tip": "Run Quick Start using guided trade strategy and objective marker.",
                "beginner_tip": "Start the run using the guided choices.",
            },
            "discover_trade_options": {
                "pro_label": "Analyze Drawings for Trade Options",
                "beginner_label": "Find Work Types from Drawings",
                "pro_tip": "Run a quick discovery pass on selected drawings and list available trades as clickable options.",
                "beginner_tip": "Scan drawings and show work-type options so no manual typing is needed.",
            },
            "guided_skip": {
                "pro_label": "Skip to Full Interface",
                "beginner_label": "Skip Guided Setup",
                "pro_tip": "Skip guided steps and use the full workflow controls.",
                "beginner_tip": "Jump to all controls now.",
            },
            "pipe_calc": {
                "pro_label": "Calc Pipe Takeoff",
                "beginner_label": "Calculate Pipe Length",
                "pro_tip": "Compute total pipe length from feet/inches, run count, and waste percentage.",
                "beginner_tip": "Calculate total pipe amount from run length and quantity.",
            },
            "concrete_calc": {
                "pro_label": "Calc Concrete/Gravel",
                "beginner_label": "Calculate Concrete Volume",
                "pro_tip": "Compute concrete/gravel volume in cubic yards with waste and rough tonnage estimate.",
                "beginner_tip": "Calculate concrete or gravel volume and rough tons.",
            },
            "carpentry_calc": {
                "pro_label": "Calc Carpentry",
                "beginner_label": "Calculate Framing",
                "pro_tip": "Estimate studs, plate linear feet, and 2x4 board feet for a framed wall.",
                "beginner_tip": "Estimate framing material counts for a wall section.",
            },
            "hvac_calc": {
                "pro_label": "Calc HVAC Sheet-Metal",
                "beginner_label": "Calculate Duct Sheet-Metal",
                "pro_tip": "Estimate round duct circumference, sheet area, and linear footage with waste.",
                "beginner_tip": "Calculate duct material area and length for HVAC takeoff.",
            },
            "heavy_calc": {
                "pro_label": "Calc Earthwork",
                "beginner_label": "Calculate Earthwork",
                "pro_tip": "Estimate bank cubic yards, loose cubic yards, and haul tonnage.",
                "beginner_tip": "Calculate cut/fill earthwork quantity and haul estimate.",
            },
            "open_full_tool": {
                "pro_label": "Open Full Tool",
                "beginner_label": "Open Full Calculator",
                "pro_tip": "Open a larger calculator window for the selected trade math workflow.",
                "beginner_tip": "Open a bigger calculator screen for this trade.",
            },
            "control_guide": {
                "pro_label": "Control Guide",
                "beginner_label": "Help: Button Guide",
                "pro_tip": "Show a complete action/shortcut guide in the output panel.",
                "beginner_tip": "Show a plain-language list of what each button does.",
            },
            "beginner_mode_toggle": {
                "pro_label": "Beginner Mode",
                "beginner_label": "Beginner Mode",
                "pro_tip": "Switch labels and tooltips to plain-language construction terms.",
                "beginner_tip": "Use simpler button names and easier help text.",
            },
            "advanced_tools_toggle": {
                "pro_label": "Advanced Tools",
                "beginner_label": "Show Advanced Tabs",
                "pro_tip": "Show advanced quality and operations tabs in the ribbon area.",
                "beginner_tip": "Turn on extra tabs with technical tools and maintenance actions.",
            },
            "dark_mode_toggle": {
                "pro_label": "Dark Mode",
                "beginner_label": "Dark Mode",
                "pro_tip": "Switch between dark and light visual modes.",
                "beginner_tip": "Turn dark colors on or off.",
            },
            "animate_banner_toggle": {
                "pro_label": "Animate Banner",
                "beginner_label": "Animate Header",
                "pro_tip": "Enable or pause header animation effects.",
                "beginner_tip": "Turn header movement on or off.",
            },
            "load_trades": {
                "pro_label": "Load Trades",
                "beginner_label": "Load Work Types",
                "pro_tip": "Fetch valid trade names from the API and refresh trade mode options.",
                "beginner_tip": "Load the list of work types this job can use.",
            },
            "validate_trades": {
                "pro_label": "Validate Trades",
                "beginner_label": "Check Work Types",
                "pro_tip": "Check your selected trades against the active analysis mode and trade catalog.",
                "beginner_tip": "Check that your chosen work types are valid.",
            },
            "browse_overrides": {
                "pro_label": "Browse",
                "beginner_label": "Pick JSON File",
                "pro_tip": "Select a sheet-overrides JSON file to apply authoritative sheet IDs/titles.",
                "beginner_tip": "Choose a fix file for sheet names and numbers.",
            },
            "publish_uploaded_specs": {
                "pro_label": "Share Uploaded Spec Files Publicly",
                "beginner_label": "Make Uploaded Specs Public",
                "pro_tip": "If enabled, newly uploaded specs are visible to other users of the same API host.",
                "beginner_tip": "Turn this on only if you want everyone on this server to reuse the uploaded spec.",
            },
            "choose_pdfs": {
                "pro_label": "Choose PDFs",
                "beginner_label": "Pick Drawing Files",
                "pro_tip": "Pick one or more drawing PDFs for analysis or async job submission.",
                "beginner_tip": "Choose the plan drawing files you want to run.",
            },
            "quick_start": {
                "pro_label": "Quick Start",
                "beginner_label": "Start Takeoff",
                "pro_tip": "Recommended one-click flow: ensure files are selected, submit async job, and auto-poll status.",
                "beginner_tip": "Main button to start the drawing takeoff in the background and watch progress automatically.",
            },
            "run_analysis": {
                "pro_label": "Run Takeoff Now",
                "beginner_label": "Run Takeoff Now",
                "pro_tip": "Run synchronous analysis and return results directly in this window.",
                "beginner_tip": "Run the takeoff now and wait here until results finish.",
            },
            "submit_async_job": {
                "pro_label": "Start Background Takeoff",
                "beginner_label": "Start Background Takeoff",
                "pro_tip": "Submit a background takeoff job and return a job ID for polling.",
                "beginner_tip": "Start the takeoff in the background so you can keep working while it runs.",
            },
            "refresh_job": {
                "pro_label": "Check Takeoff Status",
                "beginner_label": "Check Takeoff Status",
                "pro_tip": "Fetch latest status and payload for the current takeoff job.",
                "beginner_tip": "Check progress for the current background takeoff.",
            },
            "load_latest_job": {
                "pro_label": "Load Latest Job",
                "beginner_label": "Use Newest Job",
                "pro_tip": "Load the newest job from the API into the current job field.",
                "beginner_tip": "Auto-fill with the most recent job number.",
            },
            "rerun_job": {
                "pro_label": "Rerun Job",
                "beginner_label": "Run Job Again",
                "pro_tip": "Rerun a previous job using the current form inputs and stored uploads.",
                "beginner_tip": "Run the same job again with your current settings.",
            },
            "run_e2e_benchmark": {
                "pro_label": "Run End-to-End Benchmark",
                "beginner_label": "Run Full Test",
                "pro_tip": "Build templates, execute benchmark runs, and return quality comparisons.",
                "beginner_tip": "Run the full quality test flow from start to finish.",
            },
            "rerun_recommended": {
                "pro_label": "Rerun Recommended",
                "beginner_label": "Run Suggested Job",
                "pro_tip": "Create a rerun from automated trade recommendations for current job context.",
                "beginner_tip": "Run again using the tool's suggested work-type scope.",
            },
            "cancel_job": {
                "pro_label": "Cancel Job",
                "beginner_label": "Stop Job",
                "pro_tip": "Cancel the current queued or running job when possible.",
                "beginner_tip": "Stop the current background run if it is still active.",
            },
            "template_include_all_sheets": {
                "pro_label": "Template Include All Sheets",
                "beginner_label": "Use All Sheets in Template",
                "pro_tip": "Include all detected sheets when generating benchmark template output.",
                "beginner_tip": "Add every found sheet when creating the test template.",
            },
            "get_review_queue": {
                "pro_label": "Get Review Queue",
                "beginner_label": "Show Sheets to Review",
                "pro_tip": "Show low-confidence sheet IDs and items needing human review.",
                "beginner_tip": "Show places where the app is unsure and needs a quick check.",
            },
            "open_linework_view": {
                "pro_label": "Open Linework View",
                "beginner_label": "Show Drawing Lines",
                "pro_tip": "Save and open an SVG overlay of extracted vector linework for the selected sheet.",
                "beginner_tip": "Open a picture of the lines the app found on the selected drawing sheet.",
            },
            "measure_scale_visually": {
                "pro_label": "Measure Scale Visually",
                "beginner_label": "Click Measure Scale",
                "pro_tip": "Open an interactive browser review page where two clicks measure PDF units for scale calibration.",
                "beginner_tip": "Click two points on the drawing, type the real length, then preview or apply scale.",
            },
            "preview_scale_calibration": {
                "pro_label": "Preview Scale Calibration",
                "beginner_label": "Check Scale with Known Length",
                "pro_tip": "Preview feet-per-PDF-unit conversion using a selected sheet and one known dimension.",
                "beginner_tip": "Use one known drawing length to check whether the app's scale math looks right.",
            },
            "export_overrides_template": {
                "pro_label": "Export Overrides Template",
                "beginner_label": "Create Sheet Fix File",
                "pro_tip": "Generate a sheet overrides template JSON for manual correction.",
                "beginner_tip": "Create a file where you can correct sheet names/IDs.",
            },
            "export_benchmark_template": {
                "pro_label": "Export Benchmark Template",
                "beginner_label": "Create Test Template",
                "pro_tip": "Generate a benchmark manifest template from current/last completed job.",
                "beginner_tip": "Create a quality-test template from this job.",
            },
            "benchmark_include_unmapped": {
                "pro_label": "Benchmark Include Unmapped",
                "beginner_label": "Include Unnamed Sheets",
                "pro_tip": "Include unmapped sheet IDs in benchmark template expectations.",
                "beginner_tip": "Include sheets with missing IDs in the quality test.",
            },
            "run_baseline_benchmark": {
                "pro_label": "Run Baseline Benchmark",
                "beginner_label": "Run Baseline Test",
                "pro_tip": "Run a baseline benchmark using selected manifests and settings.",
                "beginner_tip": "Run a base test to compare future improvements.",
            },
            "show_benchmark_history": {
                "pro_label": "Show Benchmark History",
                "beginner_label": "Show Past Tests",
                "pro_tip": "Show saved benchmark result history from API or local fallback.",
                "beginner_tip": "Show previous quality-test runs.",
            },
            "compare_reports": {
                "pro_label": "Compare Reports",
                "beginner_label": "Compare Two Test Files",
                "pro_tip": "Pick two benchmark JSON files and compare baseline vs candidate scores.",
                "beginner_tip": "Compare two test files to see what improved or dropped.",
            },
            "compare_latest_reports": {
                "pro_label": "Compare Latest Reports",
                "beginner_label": "Compare Last Two Tests",
                "pro_tip": "Compare the two newest benchmark reports automatically.",
                "beginner_tip": "Auto-compare your two newest tests.",
            },
            "latest_trend_snapshot": {
                "pro_label": "Latest Trend Snapshot",
                "beginner_label": "Show Score Trend",
                "pro_tip": "Show current benchmark trend and overall score delta.",
                "beginner_tip": "Show whether quality is improving or getting worse.",
            },
            "score_timeline": {
                "pro_label": "Score Timeline",
                "beginner_label": "Show Score Over Time",
                "pro_tip": "Display benchmark score timeline points across saved runs.",
                "beginner_tip": "Show quality scores over time.",
            },
            "evaluate_gate": {
                "pro_label": "Evaluate Gate",
                "beginner_label": "Check Pass/Fail Rules",
                "pro_tip": "Run quality-gate checks (non-regression/improvement thresholds).",
                "beginner_tip": "Check if current quality passes required rules.",
            },
            "benchmark_dashboard": {
                "pro_label": "Benchmark Dashboard",
                "beginner_label": "Show Test Dashboard",
                "pro_tip": "Open consolidated history, timeline, trend, and gate summary payload.",
                "beginner_tip": "Show one view with all quality-test summaries.",
            },
            "auto_poll_job": {
                "pro_label": "Auto Poll Job",
                "beginner_label": "Auto-Refresh Job Status",
                "pro_tip": "Automatically refresh the current job until it reaches a terminal status.",
                "beginner_tip": "Auto-check job status until it is done.",
            },
            "save_output": {
                "pro_label": "Save Output",
                "beginner_label": "Save Results Text",
                "pro_tip": "Save the output panel content to a JSON file.",
                "beginner_tip": "Save what you see in the results panel.",
            },
            "export_takeoff_csv": {
                "pro_label": "Export Takeoff CSV",
                "beginner_label": "Export Takeoff Spreadsheet",
                "pro_tip": "Save current job quantities as CSV rows for Excel or pricing handoff.",
                "beginner_tip": "Save the takeoff as a spreadsheet file you can open in Excel.",
            },
            "show_reviewed_takeoff_lines": {
                "pro_label": "Show Reviewed Takeoff Lines",
                "beginner_label": "Show Checked Takeoff Items",
                "pro_tip": "Fetch estimator-reviewed takeoff line items with trade, item type, quantity, unit, cost code, and source sheet.",
                "beginner_tip": "Show the takeoff items you manually checked and marked to include.",
            },
            "open_selected_line_source": {
                "pro_label": "Open Selected Line Source",
                "beginner_label": "Open Checked Item on Drawing",
                "pro_tip": "Open the visual review page for the selected reviewed takeoff line item's source sheet and measurement.",
                "beginner_tip": "Open the drawing page where the selected checked item came from.",
            },
            "save_filtered_reviewed_csv": {
                "pro_label": "Save Filtered CSV",
                "beginner_label": "Save These Checked Items",
                "pro_tip": "Save only the currently filtered reviewed takeoff line items as a CSV spreadsheet.",
                "beginner_tip": "Save the checked items currently shown in the table to an Excel-friendly file.",
            },
            "save_rollup_csv": {
                "pro_label": "Save Rollup CSV",
                "beginner_label": "Save Grouped Totals",
                "pro_tip": "Save the grouped reviewed takeoff totals from the Takeoff Rollup tab as a CSV spreadsheet.",
                "beginner_tip": "Save the grouped totals table to an Excel-friendly file.",
            },
            "show_selected_rollup_detail": {
                "pro_label": "Show Selected Detail",
                "beginner_label": "Show These Measurements",
                "pro_tip": "Filter the reviewed takeoff line table to the selected grouped rollup's work type and measured item.",
                "beginner_tip": "Show the individual checked measurements that make up the selected grouped total.",
            },
            "open_estimator_report": {
                "pro_label": "Open Estimator Report",
                "beginner_label": "Open Easy Report",
                "pro_tip": "Open a browser report for current job sheets, trades, quantities, issues, and cost-code hints.",
                "beginner_tip": "Open an easier-to-read report instead of raw JSON.",
            },
            "spec_compliance": {
                "pro_label": "Spec Compliance",
                "beginner_label": "Check Specs",
                "pro_tip": "Show applied specs, detected standards, missing spec-required trades, and recommendations.",
                "beginner_tip": "Check whether the attached specs add anything that needs review.",
            },
            "export_handoff_package": {
                "pro_label": "Export Handoff Package",
                "beginner_label": "Export Job Package",
                "pro_tip": "Save a ZIP with estimator report, takeoff CSV, spec compliance JSON, result JSON, and job metadata.",
                "beginner_tip": "Save everything needed to hand off this job in one ZIP file.",
            },
            "open_results_folder": {
                "pro_label": "Open Results Folder",
                "beginner_label": "Open Results Folder",
                "pro_tip": "Open local benchmarks/results folder in your file explorer.",
                "beginner_tip": "Open the folder where test and result files are stored.",
            },
            "job_ops_snapshot": {
                "pro_label": "Job Ops Snapshot",
                "beginner_label": "Show System Snapshot",
                "pro_tip": "Show operational metrics snapshot for queue, durations, and throughput.",
                "beginner_tip": "Show system health numbers like queue size and speed.",
            },
            "job_ops_gate": {
                "pro_label": "Job Ops Gate",
                "beginner_label": "Check System Pass/Fail",
                "pro_tip": "Evaluate operational quality gate thresholds against recent job metrics.",
                "beginner_tip": "Check if system performance is inside allowed limits.",
            },
            "trade_recommendation": {
                "pro_label": "Trade Recommendation",
                "beginner_label": "Suggest Work Types",
                "pro_tip": "Generate recommended trade scope for current job based on detected content.",
                "beginner_tip": "Suggest which work types should be included for this job.",
            },
            "trade_coverage": {
                "pro_label": "Trade Coverage",
                "beginner_label": "Show Work Type Coverage",
                "pro_tip": "Show per-trade coverage and review-needed status for current job results.",
                "beginner_tip": "Show how complete each work type is in current results.",
            },
            "readiness_report": {
                "pro_label": "Readiness Report",
                "beginner_label": "Show Ready-to-Handoff Report",
                "pro_tip": "Generate handoff/readiness report combining review, coverage, and ops gates.",
                "beginner_tip": "Generate a report showing if this job is ready to hand off.",
            },
            "cleanup_uploads": {
                "pro_label": "Cleanup Uploads",
                "beginner_label": "Delete Uploaded Files Too",
                "pro_tip": "When pruning, also delete uploaded file folders tied to pruned jobs.",
                "beginner_tip": "Also delete uploaded source files during cleanup.",
            },
            "prune_dry_run": {
                "pro_label": "Prune Dry Run",
                "beginner_label": "Preview Cleanup",
                "pro_tip": "Preview jobs that would be pruned using current prune filters.",
                "beginner_tip": "Show what would be deleted without deleting anything.",
            },
            "prune_apply": {
                "pro_label": "Prune Apply",
                "beginner_label": "Run Cleanup",
                "pro_tip": "Delete/prune matching completed/failed/canceled jobs using current filters.",
                "beginner_tip": "Delete old finished jobs using your cleanup settings.",
            },
        }

    def _field_label_specs_for_ui(self) -> dict[str, dict[str, str]]:
        return {
            "api_url": {
                "pro_label": "API URL",
                "beginner_label": "Server Address",
                "pro_tip": "Base API endpoint for requests.",
                "beginner_tip": "Server address (leave as local unless your admin gave another one).",
            },
            "api_key": {
                "pro_label": "API Key (optional)",
                "beginner_label": "Security Key (optional)",
                "pro_tip": (
                    "Optional x-api-key value. Leave blank for local, unprotected instances."
                ),
                "beginner_tip": (
                    "Leave blank for local server. For protected APIs, paste the key here so jobs can connect."
                ),
            },
            "tenant_id": {
                "pro_label": "Tenant ID",
                "beginner_label": "Company Workspace",
                "pro_tip": "Tenant scope sent as x-tenant-id to keep jobs and results isolated by company/workspace.",
                "beginner_tip": "Use your company workspace ID so only your jobs/results are shown.",
            },
            "analysis_mode": {
                "pro_label": "Analysis Mode",
                "beginner_label": "Trade Selection Settings",
                "pro_tip": "Trade scope inference behavior for the job.",
                "beginner_tip": "Choose how trades are selected: all trades, auto-detect from drawings, or your own work-type list.",
            },
            "selected_trades": {
                "pro_label": "Selected Trades (CSV)",
                "beginner_label": "Chosen Work Types",
                "pro_tip": "Trade list used with selected analysis mode. Populated from checkbox options.",
                "beginner_tip": "Filled automatically from your checkbox selections.",
            },
            "overrides_path": {
                "pro_label": "Sheet Overrides JSON",
                "beginner_label": "Sheet Fix File",
                "pro_tip": "Path to a JSON file with manual sheet ID/title overrides.",
                "beginner_tip": "Pick a sheet-fix file to correct sheet names/IDs.",
            },
            "current_job": {
                "pro_label": "Current Job ID",
                "beginner_label": "Current Job Number",
                "pro_tip": "Use this value to check/cancel/rerun jobs.",
                "beginner_tip": "The job number you want to check or rerun.",
            },
            "notes": {
                "pro_label": "Notes",
                "beginner_label": "Project Notes",
                "pro_tip": "Optional notes sent with the analysis request.",
                "beginner_tip": "Optional notes for this job.",
            },
            "prune_statuses": {
                "pro_label": "Prune Statuses",
                "beginner_label": "Job Types to Remove",
                "pro_tip": "Statuses used when pruning job records.",
                "beginner_tip": "Which finished job states to clean up.",
            },
            "prune_older_than": {
                "pro_label": "Older Than (h)",
                "beginner_label": "Age in Hours",
                "pro_tip": "Only prune jobs older than this threshold.",
                "beginner_tip": "Only clean jobs older than this many hours.",
            },
            "prune_limit": {
                "pro_label": "Limit",
                "beginner_label": "Max Cleaned Jobs",
                "pro_tip": "Limit jobs evaluated per cleanup action.",
                "beginner_tip": "Maximum number of jobs cleaned in one go.",
            },
        }

    def _toggle_beginner_mode(self) -> None:
        self._apply_beginner_mode(update_status=True)
        self._save_settings()

    def _toggle_advanced_tools(self) -> None:
        self._apply_advanced_tools_visibility(update_status=True)
        self._save_settings()

    def _apply_advanced_tools_visibility(self, *, update_status: bool) -> None:
        if self.actions_notebook is None:
            return
        show_advanced = bool(self.show_advanced_tools.get())
        for tab_widget, tab_text in self._advanced_tab_widgets:
            current_state = str(self.actions_notebook.tab(tab_widget, "state"))
            desired_state = "normal" if show_advanced else "hidden"
            if current_state != desired_state:
                self.actions_notebook.tab(tab_widget, state=desired_state)
        if not show_advanced:
            self.actions_notebook.select(0)
        if update_status:
            message = "Advanced tabs shown." if show_advanced else "Advanced tabs hidden."
            self.status_text.set(message)

    def _apply_beginner_mode(self, *, update_status: bool) -> None:
        use_beginner = bool(self.beginner_mode.get())
        if use_beginner and self.show_advanced_tools.get():
            self.show_advanced_tools.set(False)
            self._apply_advanced_tools_visibility(update_status=False)
        for key, widget in self._control_widgets.items():
            spec = self._control_specs.get(key)
            if not spec:
                continue
            target_label = spec["beginner_label"] if use_beginner else spec["pro_label"]
            try:
                widget.configure(text=target_label)
            except Exception:
                pass
            tip = self._control_tooltips.get(key)
            if tip is not None:
                tip_text = spec["beginner_tip"] if use_beginner else spec["pro_tip"]
                tip.set_text(tip_text)

        for key, tip in self._field_tooltips.items():
            spec = self._field_tooltip_specs.get(key)
            if not spec:
                continue
            tip_text = spec["beginner_tip"] if use_beginner else spec["pro_tip"]
            tip.set_text(tip_text)

        for key, widget in self._field_label_widgets.items():
            spec = self._field_label_specs.get(key)
            if not spec:
                continue
            try:
                widget.configure(text=spec["beginner_label"] if use_beginner else spec["pro_label"])
            except Exception:
                pass

        for key, tip in self._field_label_tooltips.items():
            spec = self._field_label_specs.get(key)
            if not spec:
                continue
            tip_text = spec["beginner_tip"] if use_beginner else spec["pro_tip"]
            tip.set_text(tip_text)

        if self.guided_flow_frame is not None:
            if use_beginner:
                self.guided_flow_frame.grid()
            else:
                self.guided_flow_frame.grid_remove()
            self._refresh_guided_flow()
        self._set_trade_discovery_busy(self.trade_discovery_running)

        self._control_help_entries = {}
        for key, spec in self._control_specs.items():
            label = spec["beginner_label"] if use_beginner else spec["pro_label"]
            description = spec["beginner_tip"] if use_beginner else spec["pro_tip"]
            self._control_help_entries[label] = description

        if update_status:
            mode_text = "Beginner mode enabled." if use_beginner else "Beginner mode disabled."
            self.status_text.set(mode_text)

    def _sync_guided_trade_strategy(self) -> None:
        strategy = self.guided_trade_strategy.get().strip()
        if strategy in {"auto", "selected", "all"} and strategy != self.analysis_mode.get().strip():
            self.analysis_mode.set(strategy)
        if (
            strategy == "selected"
            and not self.trade_option_vars
            and self.files
            and not self.trade_discovery_running
        ):
            self.root.after(120, self._discover_trade_options_from_drawings)
        self._refresh_guided_flow()

    def _sync_analysis_mode_to_guided(self) -> None:
        mode = self.analysis_mode.get().strip()
        if mode in {"auto", "selected", "all"} and mode != self.guided_trade_strategy.get().strip():
            self.guided_trade_strategy.set(mode)

    def _refresh_guided_flow(self) -> None:
        if self.guided_flow_frame is None:
            return

        step = self.guided_step.get().strip() or "trade"
        strategy = self.guided_trade_strategy.get().strip() or "all"
        use_objective = strategy in {"all", "selected"}

        if step == "trade":
            self.guided_step_title.set("Step 1: Trade Selection Settings")
            self.guided_step_detail.set(
                "Choose All Trades, analyze drawings for available trades, or choose work types from discovered options."
            )
            if self.guided_back_button is not None:
                self.guided_back_button.state(["disabled"])
            if self.guided_proceed_button is not None:
                self.guided_proceed_button.state(["!disabled"])
            if self.guided_execute_button is not None:
                self.guided_execute_button.state(["disabled"])
            if self.guided_selected_frame is not None:
                if strategy == "selected":
                    self.guided_selected_frame.grid()
                else:
                    self.guided_selected_frame.grid_remove()
            if self.guided_objective_frame is not None:
                self.guided_objective_frame.grid_remove()
            return

        # step == "run"
        if self.guided_back_button is not None:
            self.guided_back_button.state(["!disabled"])
        if self.guided_proceed_button is not None:
            self.guided_proceed_button.state(["disabled"])
        if self.guided_execute_button is not None:
            self.guided_execute_button.state(["!disabled"])

        if strategy == "auto":
            self.guided_step_title.set("Step 2: Proceed with Trade Discovery Analysis")
            self.guided_step_detail.set(
                "The app will analyze drawings and detect available trades automatically, then run the job."
            )
        elif strategy == "selected":
            self.guided_step_title.set("Step 2: Confirm Chosen Work Types and Run")
            self.guided_step_detail.set(
                "Confirm the work-type checkboxes and run with selected trade scope. No typing required."
            )
        else:
            self.guided_step_title.set("Step 2: Choose Run Objective and Proceed")
            self.guided_step_detail.set(
                "Choose output objective, then run the job. Use Guided Back to revise trade selection."
            )

        if self.guided_selected_frame is not None:
            if strategy == "selected":
                self.guided_selected_frame.grid()
            else:
                self.guided_selected_frame.grid_remove()

        if self.guided_objective_frame is not None:
            if use_objective:
                self.guided_objective_frame.grid()
            else:
                self.guided_objective_frame.grid_remove()

    def _guided_back(self) -> None:
        self.guided_step.set("trade")

    def _guided_proceed(self) -> None:
        strategy = self.guided_trade_strategy.get().strip()
        if strategy not in {"auto", "selected", "all"}:
            self.status_text.set("Choose a trade selection setting first.")
            return
        if strategy == "selected" and not self.selected_trades.get().strip():
            if not self.trade_discovery_running:
                self._discover_trade_options_from_drawings()
            self.status_text.set(
                "Analyzing drawings to build work-type options. Choose options, then click Guided Proceed again."
            )
            return
        self.analysis_mode.set(strategy)
        self.guided_step.set("run")
        self.status_text.set("Guided step advanced. Review options, then run.")

    def _guided_objective_label(self, objective: str) -> str:
        mapping = {
            "takeoff_and_estimation": "takeoff_and_estimation",
            "takeoff_only": "takeoff_only",
            "manhours_only": "manhours_only",
        }
        return mapping.get(objective, "takeoff_and_estimation")

    def _apply_guided_objective_note(self) -> None:
        strategy = self.guided_trade_strategy.get().strip()
        if strategy not in {"all", "selected"}:
            return
        objective = self._guided_objective_label(self.guided_run_objective.get().strip())
        marker = f"[run_objective:{objective}]"
        raw_notes = self.notes.get()
        kept_lines = [
            line
            for line in raw_notes.splitlines()
            if not line.strip().startswith("[run_objective:")
        ]
        kept_lines.append(marker)
        self.notes.set("\n".join([line for line in kept_lines if line.strip()]))

    def _guided_execute(self) -> None:
        strategy = self.guided_trade_strategy.get().strip()
        if strategy not in {"auto", "selected", "all"}:
            self.status_text.set("Choose a trade selection setting first.")
            return
        if strategy == "selected" and not self.selected_trades.get().strip():
            if not self.trade_discovery_running:
                self._discover_trade_options_from_drawings()
            self.status_text.set(
                "No work types selected yet. Use discovered options, then run Guided Step."
            )
            return
        self.analysis_mode.set(strategy)
        self._apply_guided_objective_note()
        self._save_settings()
        self.status_text.set("Guided run started...")
        self._quick_start_run()

    def _guided_skip_to_full(self) -> None:
        self.guided_step.set("trade")
        self.show_advanced_tools.set(True)
        self._apply_advanced_tools_visibility(update_status=False)
        self.status_text.set("Full interface is available below. Use any workflow buttons directly.")

    def _parse_positive_number(self, raw: str, *, label: str) -> float:
        text = raw.strip()
        if not text:
            raise ValueError(f"{label} is required.")
        value = float(text)
        if value < 0:
            raise ValueError(f"{label} must be 0 or greater.")
        return value

    def _recalc_pipe_takeoff(self) -> None:
        try:
            feet = self._parse_positive_number(self.pipe_length_feet.get(), label="Pipe length (ft)")
            inches = self._parse_positive_number(self.pipe_length_inches.get(), label="Pipe length (in)")
            run_count = self._parse_positive_number(self.pipe_run_count.get(), label="Run count")
            waste_percent = self._parse_positive_number(self.pipe_waste_percent.get(), label="Waste %")

            single_run_ft = feet + (inches / 12.0)
            total_ft = single_run_ft * run_count * (1 + (waste_percent / 100.0))
            total_inches = total_ft * 12.0
            self.pipe_calc_result.set(
                f"Single run: {single_run_ft:.2f} ft | Total: {total_ft:.2f} ft ({total_inches:.1f} in)"
            )
        except Exception as exc:
            self.pipe_calc_result.set(f"Input error: {exc}")

    def _recalc_concrete_takeoff(self) -> None:
        try:
            length_ft = self._parse_positive_number(self.concrete_length_feet.get(), label="Length (ft)")
            width_ft = self._parse_positive_number(self.concrete_width_feet.get(), label="Width (ft)")
            depth_in = self._parse_positive_number(self.concrete_depth_inches.get(), label="Depth (in)")
            waste_percent = self._parse_positive_number(self.concrete_waste_percent.get(), label="Waste %")

            depth_ft = depth_in / 12.0
            cubic_feet = length_ft * width_ft * depth_ft
            cubic_yards = cubic_feet / 27.0
            with_waste_yards = cubic_yards * (1 + (waste_percent / 100.0))
            # Approximation for dense-graded gravel / concrete tonnage planning.
            tons_estimate = with_waste_yards * 1.4
            self.concrete_calc_result.set(
                f"Volume: {with_waste_yards:.2f} yd^3 ({cubic_feet:.1f} ft^3 base) | Approx tons: {tons_estimate:.2f}"
            )
        except Exception as exc:
            self.concrete_calc_result.set(f"Input error: {exc}")

    def _recalc_hvac_takeoff(self) -> None:
        try:
            diameter_in = self._parse_positive_number(
                self.hvac_diameter_inches.get(),
                label="Duct diameter (in)",
            )
            run_length_ft = self._parse_positive_number(
                self.hvac_run_length_feet.get(),
                label="Run length (ft)",
            )
            run_count = self._parse_positive_number(
                self.hvac_run_count.get(),
                label="Run count",
            )
            waste_percent = self._parse_positive_number(
                self.hvac_waste_percent.get(),
                label="Waste %",
            )
            if diameter_in <= 0:
                raise ValueError("Duct diameter must be greater than zero.")
            circumference_ft = (math.pi * diameter_in) / 12.0
            area_sqft_per_run = circumference_ft * run_length_ft
            total_area_sqft = area_sqft_per_run * run_count
            total_with_waste = total_area_sqft * (1 + (waste_percent / 100.0))
            linear_ft = run_length_ft * run_count * (1 + (waste_percent / 100.0))
            self.hvac_calc_result.set(
                f"Sheet area: {total_with_waste:.1f} sq ft | Linear: {linear_ft:.1f} ft | Circ: {circumference_ft:.2f} ft"
            )
        except Exception as exc:
            self.hvac_calc_result.set(f"Input error: {exc}")

    def _recalc_heavy_takeoff(self) -> None:
        try:
            area_sqft = self._parse_positive_number(
                self.heavy_area_sqft.get(),
                label="Area (sq ft)",
            )
            depth_in = self._parse_positive_number(
                self.heavy_depth_inches.get(),
                label="Depth (in)",
            )
            swell_percent = self._parse_positive_number(
                self.heavy_swell_percent.get(),
                label="Swell %",
            )
            depth_ft = depth_in / 12.0
            bank_cuft = area_sqft * depth_ft
            bank_cy = bank_cuft / 27.0
            loose_cy = bank_cy * (1 + (swell_percent / 100.0))
            # Practical planning factor for mixed native soils.
            haul_tons = loose_cy * 1.35
            self.heavy_calc_result.set(
                f"Bank: {bank_cy:.2f} yd^3 | Loose: {loose_cy:.2f} yd^3 | Haul est: {haul_tons:.2f} tons"
            )
        except Exception as exc:
            self.heavy_calc_result.set(f"Input error: {exc}")

    def _recalc_carpentry_takeoff(self) -> None:
        try:
            wall_length_ft = self._parse_positive_number(
                self.carpentry_wall_length_feet.get(),
                label="Wall length (ft)",
            )
            wall_height_ft = self._parse_positive_number(
                self.carpentry_wall_height_feet.get(),
                label="Wall height (ft)",
            )
            stud_spacing_in = self._parse_positive_number(
                self.carpentry_stud_spacing_inches.get(),
                label="Stud spacing (in)",
            )
            waste_percent = self._parse_positive_number(
                self.carpentry_waste_percent.get(),
                label="Waste %",
            )
            if stud_spacing_in <= 0:
                raise ValueError("Stud spacing (in) must be greater than zero.")

            wall_length_in = wall_length_ft * 12.0
            stud_count_base = math.ceil(wall_length_in / stud_spacing_in) + 1
            stud_count = math.ceil(stud_count_base * (1 + (waste_percent / 100.0)))
            plate_lf = (2.0 * wall_length_ft) * (1 + (waste_percent / 100.0))
            stud_lf = stud_count * wall_height_ft
            board_feet = stud_count * ((2.0 * 4.0 * wall_height_ft) / 12.0)
            self.carpentry_calc_result.set(
                f"Studs: {stud_count} | Plate LF: {plate_lf:.1f} | Stud LF: {stud_lf:.1f} | 2x4 BF: {board_feet:.1f}"
            )
        except Exception as exc:
            self.carpentry_calc_result.set(f"Input error: {exc}")

    def _safe_eval_expression(self, expression: str) -> float:
        cleaned = expression.strip().replace("x", "*").replace("X", "*").replace("÷", "/")
        if not cleaned:
            return 0.0
        if not re.fullmatch(r"[0-9\\.+\\-*/()\\s%]+", cleaned):
            raise ValueError("Unsupported expression.")
        cleaned = cleaned.replace("%", "/100")
        return float(eval(cleaned, {"__builtins__": {}}, {}))

    def _display_value_to_float(self, text: str) -> float:
        raw = text.strip()
        if not raw:
            return 0.0
        try:
            return self._safe_eval_expression(raw)
        except Exception:
            return float(raw)

    def _format_device_value(self, value: float) -> str:
        if not math.isfinite(value):
            return "0"
        return f"{value:.8f}".rstrip("0").rstrip(".")

    def _open_full_calculator(self, calculator_key: str) -> None:
        existing = self._calculator_popups.get(calculator_key)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass
            self._calculator_popups.pop(calculator_key, None)

        configs: dict[str, dict[str, object]] = {
            "pipe": {
                "title": "Pipe Trades Pro Full Tool",
                "result_var": self.pipe_calc_result,
                "compute": self._recalc_pipe_takeoff,
                "notes": "Pipe offset, travel, angle, trig, unit conversions, and run takeoff.",
                "case_bg": "#1A1D24",
                "display_bg": "#D9E3DD",
                "display_fg": "#0C1411",
                "accent": "#C0392B",
                "fields": [
                    ("Length (ft)", self.pipe_length_feet),
                    ("Length (in)", self.pipe_length_inches),
                    ("Run Count", self.pipe_run_count),
                    ("Waste %", self.pipe_waste_percent),
                ],
                "trade_keys": [
                    ("Angle/Slope", "PIPE_ANGLE"),
                    ("Offset", "PIPE_OFFSET"),
                    ("Run", "PIPE_RUN"),
                    ("Travel", "PIPE_TRAVEL"),
                    ("Ft->In", "FT_TO_IN"),
                    ("In->Ft", "IN_TO_FT"),
                    ("Circle", "CIRCLE_C"),
                    ("Takeoff", "RUN_SUMMARY"),
                ],
            },
            "concrete": {
                "title": "ConcreteCalc Pro Full Tool",
                "result_var": self.concrete_calc_result,
                "compute": self._recalc_concrete_takeoff,
                "notes": "Concrete/gravel volume, area, bag count, tonnage, and rebar planning.",
                "case_bg": "#9AB939",
                "display_bg": "#DFE6D8",
                "display_fg": "#101411",
                "accent": "#3E5A1A",
                "fields": [
                    ("Length (ft)", self.concrete_length_feet),
                    ("Width (ft)", self.concrete_width_feet),
                    ("Depth (in)", self.concrete_depth_inches),
                    ("Waste %", self.concrete_waste_percent),
                ],
                "trade_keys": [
                    ("Sq Ft", "CONC_AREA"),
                    ("Volume", "CONC_VOL"),
                    ("Bags", "CONC_BAGS"),
                    ("Tons", "CONC_TONS"),
                    ("Rebar", "CONC_REBAR"),
                    ("Sq-Up", "SQUARE"),
                    ("sqrt", "SQRT"),
                    ("Takeoff", "RUN_SUMMARY"),
                ],
            },
            "hvac": {
                "title": "Sheet Metal / HVAC Pro Full Tool",
                "result_var": self.hvac_calc_result,
                "compute": self._recalc_hvac_takeoff,
                "notes": "Duct circumference, area, CFM/FPM conversions, and sheet-metal takeoff.",
                "case_bg": "#D8B640",
                "display_bg": "#DEE2D3",
                "display_fg": "#111612",
                "accent": "#B9372A",
                "fields": [
                    ("Duct Diameter (in)", self.hvac_diameter_inches),
                    ("Run Length (ft)", self.hvac_run_length_feet),
                    ("Run Count", self.hvac_run_count),
                    ("Waste %", self.hvac_waste_percent),
                ],
                "trade_keys": [
                    ("Circ", "HVAC_CIRC"),
                    ("Area", "HVAC_AREA"),
                    ("CFM/FPM", "HVAC_CFM_TO_FPM"),
                    ("FPM/CFM", "HVAC_FPM_TO_CFM"),
                    ("x^2", "SQUARE"),
                    ("sqrt", "SQRT"),
                    ("Sin", "SIN"),
                    ("Takeoff", "RUN_SUMMARY"),
                ],
            },
            "heavy": {
                "title": "HeavyCalc Pro Full Tool",
                "result_var": self.heavy_calc_result,
                "compute": self._recalc_heavy_takeoff,
                "notes": "Cut/fill bank and loose CY, shrink/swell, and haul tonnage planning.",
                "case_bg": "#D48B2F",
                "display_bg": "#DFE3D8",
                "display_fg": "#121411",
                "accent": "#57626F",
                "fields": [
                    ("Area (sq ft)", self.heavy_area_sqft),
                    ("Depth (in)", self.heavy_depth_inches),
                    ("Swell %", self.heavy_swell_percent),
                ],
                "trade_keys": [
                    ("Bank CY", "HEAVY_BANK"),
                    ("Loose CY", "HEAVY_LOOSE"),
                    ("Shrink CY", "HEAVY_SHRINK"),
                    ("Haul Tons", "HEAVY_TONS"),
                    ("x^2", "SQUARE"),
                    ("sqrt", "SQRT"),
                    ("%", "PERCENT"),
                    ("Takeoff", "RUN_SUMMARY"),
                ],
            },
            "carpentry": {
                "title": "Carpentry Framing Full Calculator",
                "result_var": self.carpentry_calc_result,
                "compute": self._recalc_carpentry_takeoff,
                "notes": "Framing studs, plate LF, stud LF, and board-feet calculations.",
                "case_bg": "#4B5563",
                "display_bg": "#E5E7EB",
                "display_fg": "#111827",
                "accent": "#22C55E",
                "fields": [
                    ("Wall Length (ft)", self.carpentry_wall_length_feet),
                    ("Wall Height (ft)", self.carpentry_wall_height_feet),
                    ("Stud Spacing (in)", self.carpentry_stud_spacing_inches),
                    ("Waste %", self.carpentry_waste_percent),
                ],
                "trade_keys": [
                    ("Stud Count", "CARP_STUDS"),
                    ("Board Feet", "CARP_BF"),
                    ("Plate LF", "CARP_PLATE"),
                    ("Stud LF", "CARP_STUD_LF"),
                    ("x^2", "SQUARE"),
                    ("sqrt", "SQRT"),
                    ("%", "PERCENT"),
                    ("Takeoff", "RUN_SUMMARY"),
                ],
            },
        }
        config = configs.get(calculator_key)
        if config is None:
            return

        popup = Toplevel(self.root)
        popup.title(str(config["title"]))
        popup.geometry("980x700")
        popup.minsize(900, 620)
        popup.configure(background=_THEME["app_bg"])
        self._calculator_popups[calculator_key] = popup

        calc_canvas, calc_surface = self._build_scrollable_surface(
            parent=popup,
            container_style="App.TFrame",
            padding=(14, 14, 14, 14),
            canvas_background=_THEME["app_bg"],
            min_width=860,
            min_height=560,
        )
        calc_canvas.configure(yscrollincrement=14, xscrollincrement=14)
        calc_surface.columnconfigure(0, weight=1)
        calc_surface.rowconfigure(0, weight=1)

        shell = Frame(
            calc_surface,
            background=str(config["case_bg"]),
            bd=4,
            relief="ridge",
            padx=14,
            pady=14,
        )
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(0, weight=3)
        shell.grid_columnconfigure(1, weight=2)
        shell.grid_rowconfigure(3, weight=1)

        Label(
            shell,
            text=str(config["title"]),
            font=("Segoe UI Semibold", 16),
            background=str(config["case_bg"]),
            foreground="#F8FAFC",
            anchor="w",
        ).grid(
            row=0, column=0, sticky="w"
        )

        display_var = StringVar(value="0")
        info_var = StringVar(value="Ready")
        memory = {"value": 0.0}

        Label(
            shell,
            textvariable=display_var,
            background=str(config["display_bg"]),
            foreground=str(config["display_fg"]),
            font=("Consolas", 28, "bold"),
            anchor="e",
            padx=14,
            pady=10,
            relief="sunken",
            bd=2,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        Label(
            shell,
            textvariable=info_var,
            background=str(config["case_bg"]),
            foreground="#E2E8F0",
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 10))

        input_panel = ttk.LabelFrame(shell, text="Trade Inputs", padding=10)
        input_panel.grid(row=3, column=0, sticky="nsew", padx=(0, 10))
        input_panel.columnconfigure(1, weight=1)
        fields = config.get("fields")
        if isinstance(fields, list):
            for idx, item in enumerate(fields):
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                label_text, value_var = item
                ttk.Label(input_panel, text=str(label_text)).grid(row=idx, column=0, sticky="w", pady=(0, 4))
                ttk.Entry(input_panel, textvariable=value_var, width=18).grid(row=idx, column=1, sticky="ew", pady=(0, 4))

        aux_rise = StringVar(value="0")
        aux_run = StringVar(value="0")
        aux_roll = StringVar(value="0")
        aux_angle = StringVar(value="45")
        ttk.Label(input_panel, text="Rise").grid(row=6, column=0, sticky="w", pady=(4, 2))
        ttk.Entry(input_panel, textvariable=aux_rise).grid(row=6, column=1, sticky="ew", pady=(4, 2))
        ttk.Label(input_panel, text="Run / Area").grid(row=7, column=0, sticky="w", pady=(0, 2))
        ttk.Entry(input_panel, textvariable=aux_run).grid(row=7, column=1, sticky="ew", pady=(0, 2))
        ttk.Label(input_panel, text="Roll").grid(row=8, column=0, sticky="w", pady=(0, 2))
        ttk.Entry(input_panel, textvariable=aux_roll).grid(row=8, column=1, sticky="ew", pady=(0, 2))
        ttk.Label(input_panel, text="Angle / Shrink %").grid(row=9, column=0, sticky="w", pady=(0, 2))
        ttk.Entry(input_panel, textvariable=aux_angle).grid(row=9, column=1, sticky="ew", pady=(0, 2))

        keys_panel = Frame(shell, background=str(config["case_bg"]))
        keys_panel.grid(row=3, column=1, sticky="nsew")
        for col in range(4):
            keys_panel.grid_columnconfigure(col, weight=1)
        for row in range(10):
            keys_panel.grid_rowconfigure(row, weight=1)

        def set_display(value: float) -> None:
            display_var.set(self._format_device_value(value))

        def get_display() -> float:
            return self._display_value_to_float(display_var.get())

        def set_info(message: str) -> None:
            info_var.set(message)

        def append_token(token: str) -> None:
            current = display_var.get().strip()
            if current in {"0", "Error"} and token not in {".", "+", "-", "*", "/"}:
                display_var.set(token)
            else:
                display_var.set(f"{current}{token}")

        def apply_summary() -> None:
            run_fn = config.get("compute")
            if callable(run_fn):
                run_fn()
            result_var = config.get("result_var")
            if isinstance(result_var, StringVar):
                set_info(result_var.get())

        def domain(action: str) -> None:
            try:
                value = get_display()
                rise = self._parse_positive_number(aux_rise.get(), label="Rise")
                run = self._parse_positive_number(aux_run.get(), label="Run/Area")
                roll = self._parse_positive_number(aux_roll.get(), label="Roll")
                angle = self._parse_positive_number(aux_angle.get(), label="Angle")
                if action == "SQUARE":
                    set_display(value * value)
                    set_info("Squared.")
                elif action == "SQRT":
                    set_display(math.sqrt(max(value, 0.0)))
                    set_info("Square root.")
                elif action == "SIN":
                    set_display(math.sin(math.radians(value)))
                    set_info("Sine (degrees).")
                elif action == "COS":
                    set_display(math.cos(math.radians(value)))
                    set_info("Cosine (degrees).")
                elif action == "TAN":
                    set_display(math.tan(math.radians(value)))
                    set_info("Tangent (degrees).")
                elif action == "PERCENT":
                    set_display(value / 100.0)
                    set_info("Percent applied.")
                elif action == "FT_TO_IN":
                    set_display(value * 12.0)
                    set_info("Feet to inches.")
                elif action == "IN_TO_FT":
                    set_display(value / 12.0)
                    set_info("Inches to feet.")
                elif action == "CIRCLE_C":
                    set_display(math.pi * value)
                    set_info("Circumference from diameter.")
                elif action == "PIPE_ANGLE":
                    if run <= 0:
                        raise ValueError("Run must be > 0.")
                    set_display(math.degrees(math.atan(rise / run)))
                    set_info("Pipe angle from rise/run.")
                elif action == "PIPE_OFFSET":
                    set_display(math.sqrt((rise * rise) + (roll * roll)))
                    set_info("True offset from rise/roll.")
                elif action == "PIPE_TRAVEL":
                    true_offset = math.sqrt((rise * rise) + (roll * roll))
                    if angle <= 0:
                        raise ValueError("Angle must be > 0.")
                    set_display(true_offset / math.sin(math.radians(angle)))
                    set_info("Travel length.")
                elif action == "PIPE_RUN":
                    if angle <= 0:
                        raise ValueError("Angle must be > 0.")
                    set_display(rise / math.tan(math.radians(angle)))
                    set_info("Run from rise/angle.")
                elif action == "CONC_AREA":
                    length = self._parse_positive_number(self.concrete_length_feet.get(), label="Length")
                    width = self._parse_positive_number(self.concrete_width_feet.get(), label="Width")
                    set_display(length * width)
                    set_info("Concrete area (sq ft).")
                elif action == "CONC_VOL":
                    length = self._parse_positive_number(self.concrete_length_feet.get(), label="Length")
                    width = self._parse_positive_number(self.concrete_width_feet.get(), label="Width")
                    depth = self._parse_positive_number(self.concrete_depth_inches.get(), label="Depth")
                    set_display((length * width * (depth / 12.0)) / 27.0)
                    set_info("Concrete volume (yd^3).")
                elif action == "CONC_BAGS":
                    length = self._parse_positive_number(self.concrete_length_feet.get(), label="Length")
                    width = self._parse_positive_number(self.concrete_width_feet.get(), label="Width")
                    depth = self._parse_positive_number(self.concrete_depth_inches.get(), label="Depth")
                    set_display(math.ceil((length * width * (depth / 12.0)) / 0.60))
                    set_info("Approx 80-lb bag count.")
                elif action == "CONC_TONS":
                    length = self._parse_positive_number(self.concrete_length_feet.get(), label="Length")
                    width = self._parse_positive_number(self.concrete_width_feet.get(), label="Width")
                    depth = self._parse_positive_number(self.concrete_depth_inches.get(), label="Depth")
                    waste = self._parse_positive_number(self.concrete_waste_percent.get(), label="Waste %")
                    yards = (length * width * (depth / 12.0)) / 27.0
                    set_display(yards * (1 + (waste / 100.0)) * 1.4)
                    set_info("Approx aggregate tons.")
                elif action == "CONC_REBAR":
                    if run <= 0:
                        raise ValueError("Run/Area should hold spacing (in).")
                    area = self._parse_positive_number(self.concrete_length_feet.get(), label="Length") * self._parse_positive_number(self.concrete_width_feet.get(), label="Width")
                    set_display((area / (run / 12.0)) * 2.0)
                    set_info("Approx rebar LF.")
                elif action == "HVAC_CIRC":
                    diameter = self._parse_positive_number(self.hvac_diameter_inches.get(), label="Diameter")
                    set_display((math.pi * diameter) / 12.0)
                    set_info("Duct circumference (ft).")
                elif action == "HVAC_AREA":
                    diameter = self._parse_positive_number(self.hvac_diameter_inches.get(), label="Diameter")
                    length = self._parse_positive_number(self.hvac_run_length_feet.get(), label="Run length")
                    count = self._parse_positive_number(self.hvac_run_count.get(), label="Run count")
                    set_display(((math.pi * diameter) / 12.0) * length * count)
                    set_info("Duct area (sq ft).")
                elif action == "HVAC_CFM_TO_FPM":
                    if run <= 0:
                        raise ValueError("Run/Area should hold duct area (sq ft).")
                    set_display(value / run)
                    set_info("FPM from CFM / area.")
                elif action == "HVAC_FPM_TO_CFM":
                    if run <= 0:
                        raise ValueError("Run/Area should hold duct area (sq ft).")
                    set_display(value * run)
                    set_info("CFM from FPM * area.")
                elif action == "HEAVY_BANK":
                    area = self._parse_positive_number(self.heavy_area_sqft.get(), label="Area")
                    depth = self._parse_positive_number(self.heavy_depth_inches.get(), label="Depth")
                    set_display((area * (depth / 12.0)) / 27.0)
                    set_info("Bank CY.")
                elif action == "HEAVY_LOOSE":
                    area = self._parse_positive_number(self.heavy_area_sqft.get(), label="Area")
                    depth = self._parse_positive_number(self.heavy_depth_inches.get(), label="Depth")
                    swell = self._parse_positive_number(self.heavy_swell_percent.get(), label="Swell %")
                    bank = (area * (depth / 12.0)) / 27.0
                    set_display(bank * (1 + (swell / 100.0)))
                    set_info("Loose CY.")
                elif action == "HEAVY_SHRINK":
                    area = self._parse_positive_number(self.heavy_area_sqft.get(), label="Area")
                    depth = self._parse_positive_number(self.heavy_depth_inches.get(), label="Depth")
                    bank = (area * (depth / 12.0)) / 27.0
                    set_display(bank * (1 - (angle / 100.0)))
                    set_info("Shrink CY from angle input %.") 
                elif action == "HEAVY_TONS":
                    area = self._parse_positive_number(self.heavy_area_sqft.get(), label="Area")
                    depth = self._parse_positive_number(self.heavy_depth_inches.get(), label="Depth")
                    swell = self._parse_positive_number(self.heavy_swell_percent.get(), label="Swell %")
                    bank = (area * (depth / 12.0)) / 27.0
                    set_display(bank * (1 + (swell / 100.0)) * 1.35)
                    set_info("Haul tons.")
                elif action == "CARP_STUDS":
                    self._recalc_carpentry_takeoff()
                    set_info(self.carpentry_calc_result.get())
                elif action == "CARP_BF":
                    length = self._parse_positive_number(self.carpentry_wall_length_feet.get(), label="Length")
                    height = self._parse_positive_number(self.carpentry_wall_height_feet.get(), label="Height")
                    spacing = self._parse_positive_number(self.carpentry_stud_spacing_inches.get(), label="Spacing")
                    waste = self._parse_positive_number(self.carpentry_waste_percent.get(), label="Waste %")
                    studs = math.ceil(((length * 12.0) / spacing) + 1)
                    studs = math.ceil(studs * (1 + (waste / 100.0)))
                    set_display(studs * ((2.0 * 4.0 * height) / 12.0))
                    set_info("Board feet.")
                elif action == "CARP_PLATE":
                    length = self._parse_positive_number(self.carpentry_wall_length_feet.get(), label="Length")
                    waste = self._parse_positive_number(self.carpentry_waste_percent.get(), label="Waste %")
                    set_display((length * 2.0) * (1 + (waste / 100.0)))
                    set_info("Plate LF.")
                elif action == "CARP_STUD_LF":
                    length = self._parse_positive_number(self.carpentry_wall_length_feet.get(), label="Length")
                    height = self._parse_positive_number(self.carpentry_wall_height_feet.get(), label="Height")
                    spacing = self._parse_positive_number(self.carpentry_stud_spacing_inches.get(), label="Spacing")
                    waste = self._parse_positive_number(self.carpentry_waste_percent.get(), label="Waste %")
                    studs = math.ceil(((length * 12.0) / spacing) + 1)
                    studs = math.ceil(studs * (1 + (waste / 100.0)))
                    set_display(studs * height)
                    set_info("Stud LF.")
                elif action == "RUN_SUMMARY":
                    apply_summary()
            except Exception as exc:
                set_info(f"Function error: {exc}")

        def press(action: str) -> None:
            try:
                if action in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "."}:
                    append_token(action)
                    return
                if action in {"+", "-", "*", "/"}:
                    append_token(action)
                    return
                if action == "=":
                    set_display(self._safe_eval_expression(display_var.get()))
                    set_info("Expression solved.")
                    return
                if action in {"C", "CE"}:
                    display_var.set("0")
                    set_info("Cleared.")
                    return
                if action == "BS":
                    current = display_var.get().strip()
                    display_var.set(current[:-1] if len(current) > 1 else "0")
                    return
                if action == "+/-":
                    set_display(-get_display())
                    return
                if action == "PI":
                    append_token(str(math.pi))
                    return
                if action == "MC":
                    memory["value"] = 0.0
                    set_info("Memory cleared.")
                    return
                if action == "MR":
                    set_display(float(memory["value"]))
                    set_info("Memory recalled.")
                    return
                if action == "MS":
                    memory["value"] = get_display()
                    set_info("Memory stored.")
                    return
                if action == "M+":
                    memory["value"] = float(memory["value"]) + get_display()
                    set_info("Memory add.")
                    return
                if action.startswith("FN:"):
                    domain(action[3:])
            except Exception as exc:
                display_var.set("Error")
                set_info(f"Calc error: {exc}")

        trade_keys = config.get("trade_keys")
        if isinstance(trade_keys, list):
            for idx, row in enumerate(trade_keys):
                if not isinstance(row, tuple) or len(row) != 2:
                    continue
                title, action = row
                r = idx // 4
                c = idx % 4
                Button(
                    keys_panel,
                    text=str(title),
                    command=lambda v=str(action): press(f"FN:{v}"),
                    background=str(config["accent"]),
                    foreground="#F8FAFC",
                    activebackground="#334155",
                    activeforeground="#F8FAFC",
                    relief="raised",
                    bd=2,
                    font=("Segoe UI Semibold", 10),
                ).grid(row=r, column=c, sticky="nsew", padx=3, pady=3)

        keypad_layout = [
            [("MC", "MC"), ("MR", "MR"), ("MS", "MS"), ("M+", "M+")],
            [("7", "7"), ("8", "8"), ("9", "9"), ("÷", "/")],
            [("4", "4"), ("5", "5"), ("6", "6"), ("x", "*")],
            [("1", "1"), ("2", "2"), ("3", "3"), ("-", "-")],
            [("0", "0"), (".", "."), ("=", "="), ("+", "+")],
            [("C", "C"), ("CE", "CE"), ("<-", "BS"), ("+/-", "+/-")],
            [("pi", "PI"), ("sin", "FN:SIN"), ("cos", "FN:COS"), ("tan", "FN:TAN")],
        ]
        row_start = 3
        for r_idx, row in enumerate(keypad_layout):
            for c_idx, (title, action) in enumerate(row):
                is_op = action in {"+", "-", "*", "/", "="}
                Button(
                    keys_panel,
                    text=title,
                    command=lambda v=action: press(v),
                    background="#1F2937" if is_op else "#111827",
                    foreground="#FDE68A" if is_op else "#F8FAFC",
                    activebackground="#334155",
                    activeforeground="#F8FAFC",
                    relief="raised",
                    bd=2,
                    font=("Segoe UI Semibold", 11),
                ).grid(row=row_start + r_idx, column=c_idx, sticky="nsew", padx=3, pady=3)

        footer_row = Frame(shell, background=str(config["case_bg"]))
        footer_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        footer_row.grid_columnconfigure(0, weight=1)
        footer_row.grid_columnconfigure(1, weight=1)
        ttk.Button(
            footer_row,
            text="Run Takeoff Update",
            style="Primary.TButton",
            command=apply_summary,
        ).grid(row=0, column=0, sticky="w")
        close_button = ttk.Button(footer_row, text="Close")
        close_button.grid(row=0, column=1, sticky="e")

        def _cleanup_popup() -> None:
            self._calculator_popups.pop(calculator_key, None)
            popup.destroy()

        close_button.configure(command=_cleanup_popup)
        popup.protocol("WM_DELETE_WINDOW", _cleanup_popup)

    def _walk_widgets(self, parent: object) -> list[object]:
        children = []
        winfo_children = getattr(parent, "winfo_children", None)
        if not callable(winfo_children):
            return children
        for child in winfo_children():
            children.append(child)
            children.extend(self._walk_widgets(child))
        return children

    def _add_tooltip(self, widget: object, text: str) -> HoverTooltip | None:
        if not text.strip():
            return None
        tooltip = HoverTooltip(widget, text)
        self._tooltips.append(tooltip)
        return tooltip

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F1>", self._shortcut_show_guide, add="+")
        self.root.bind("<Control-o>", self._shortcut_choose_pdfs, add="+")
        self.root.bind("<Control-Return>", self._shortcut_submit_job, add="+")
        self.root.bind("<Control-Shift-Return>", self._shortcut_quick_start, add="+")
        self.root.bind("<F5>", self._shortcut_refresh_job, add="+")
        self.root.bind("<Control-l>", self._shortcut_load_latest_job, add="+")
        self.root.bind("<Control-s>", self._shortcut_save_output, add="+")
        self.root.bind("<Control-b>", self._shortcut_toggle_beginner_mode, add="+")

    def _shortcut_show_guide(self, _event: object = None) -> str:
        self._show_control_guide()
        return "break"

    def _shortcut_choose_pdfs(self, _event: object = None) -> str:
        self._choose_pdfs()
        return "break"

    def _shortcut_submit_job(self, _event: object = None) -> str:
        self._submit_async_job()
        return "break"

    def _shortcut_quick_start(self, _event: object = None) -> str:
        self._quick_start_run()
        return "break"

    def _shortcut_refresh_job(self, _event: object = None) -> str:
        self._refresh_job()
        return "break"

    def _shortcut_load_latest_job(self, _event: object = None) -> str:
        self._load_latest_job()
        return "break"

    def _shortcut_save_output(self, _event: object = None) -> str:
        self._save_output()
        return "break"

    def _shortcut_toggle_beginner_mode(self, _event: object = None) -> str:
        self.beginner_mode.set(not bool(self.beginner_mode.get()))
        self._toggle_beginner_mode()
        return "break"

    def _show_control_guide(self) -> None:
        use_beginner = bool(self.beginner_mode.get())
        heading = "EstimateForge - Beginner Guide" if use_beginner else "EstimateForge - Control Guide"
        label_mode = "beginner_label" if use_beginner else "pro_label"
        choose_pdfs_label = self._control_specs.get("choose_pdfs", {}).get(label_mode, "Choose PDFs")
        submit_job_label = self._control_specs.get("submit_async_job", {}).get(label_mode, "Submit Async Job")
        refresh_job_label = self._control_specs.get("refresh_job", {}).get(label_mode, "Refresh Job")
        load_latest_label = self._control_specs.get("load_latest_job", {}).get(label_mode, "Load Latest Job")
        save_output_label = self._control_specs.get("save_output", {}).get(label_mode, "Save Output")
        beginner_mode_label = self._control_specs.get("beginner_mode_toggle", {}).get(label_mode, "Beginner Mode")
        lines = [
            heading,
            "",
            "API key is only required when your API endpoint is protected (local default usually is not).",
            "Guided start: Step 1 sets trade strategy; selected mode auto-scans drawings and shows clickable work-type options.",
            "Then Step 2 confirms objective and runs Quick Start.",
            "Keyboard shortcuts:",
            "- F1: Show this guide",
            f"- Ctrl+O: {choose_pdfs_label}",
            f"- Ctrl+Enter: {submit_job_label}",
            "- Ctrl+Shift+Enter: Quick Start",
            f"- F5: {refresh_job_label}",
            f"- Ctrl+L: {load_latest_label}",
            f"- Ctrl+S: {save_output_label}",
            f"- Ctrl+B: Toggle {beginner_mode_label}",
            "",
            "Controls:",
        ]
        if self._control_help_entries:
            for name, description in self._control_help_entries.items():
                lines.append(f"- {name}: {description}")
        else:
            lines.append("- No control descriptions were found.")

        self._set_output_text("\n".join(lines))
        self.status_text.set("Guide loaded.")

    def _choose_pdfs(self) -> None:
        selected = filedialog.askopenfilenames(
            title="Select drawing PDFs",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        self.files = list(selected)
        self._file_scan_meta = {}
        self._file_scan_token += 1
        self._refresh_files_label()
        self.status_text.set("PDFs selected." if self.files else "No PDFs selected.")
        if self.files:
            self._start_selected_file_scan(self.files)
            if (
                self.guided_trade_strategy.get().strip() == "selected"
                and not self.trade_discovery_running
            ):
                self.root.after(200, self._discover_trade_options_from_drawings)
        self._save_settings()

    def _start_selected_file_scan(self, file_paths: list[str]) -> None:
        if not file_paths:
            self._set_file_scan_busy(busy=False)
            return
        paths = [str(Path(p).resolve()) for p in file_paths if str(p).strip()]
        if not paths:
            return

        self._append_output_line(
            f"Scanning {len(paths)} selected drawing file(s) for metadata (size and pages)..."
        )
        self._set_file_scan_busy(
            busy=True,
            message="Scanning selected drawing files (this usually takes seconds)...",
        )
        self._set_file_scan_message()
        worker = Thread(
            target=self._scan_selected_files_worker,
            args=(paths, self._file_scan_token),
            daemon=True,
        )
        worker.start()

    def _scan_selected_files_worker(self, file_paths: list[str], token: int) -> None:
        scanned_ok = 0
        for index, raw_path in enumerate(file_paths, start=1):
            if token != self._file_scan_token:
                return
            normalized = str(Path(raw_path).resolve())
            try:
                page_count = self._resolve_pdf_page_count(raw_path)
                self.root.after(
                    0,
                    lambda p=normalized, pages=page_count, i=index, n=len(file_paths): self._record_file_scan_result(
                        file_path=p,
                        status="ok",
                        page_count=pages,
                        error=None,
                        token=token,
                        position=i,
                        total=n,
                    ),
                )
                scanned_ok += 1
            except Exception as exc:
                self.root.after(
                    0,
                    lambda p=normalized, err=str(exc), i=index, n=len(file_paths): self._record_file_scan_result(
                        file_path=p,
                        status="error",
                        page_count=None,
                        error=err,
                        token=token,
                        position=i,
                        total=n,
                    ),
                )

        self.root.after(
            0,
            lambda: self._finalize_file_scan(token=token, scanned=scanned_ok, total=len(file_paths)),
        )

    def _resolve_pdf_page_count(self, raw_path: str) -> int:
        from pypdf import PdfReader  # local import to avoid import-time dependency on UI startup

        path = Path(raw_path)
        with path.open("rb") as handle:
            reader = PdfReader(handle, strict=False)
            return len(reader.pages)

    def _record_file_scan_result(
        self,
        *,
        file_path: str,
        status: str,
        page_count: int | None,
        error: str | None,
        token: int,
        position: int,
        total: int,
    ) -> None:
        if token != self._file_scan_token:
            return
        self._file_scan_meta[file_path] = {
            "status": status,
            "page_count": page_count if isinstance(page_count, int) else None,
            "error": error,
            "position": position,
            "total": total,
        }
        if status == "ok":
            status_message = (
                f"[{position}/{total}] Ready: {Path(file_path).name} "
                f"({page_count if page_count is not None else '??'} pages)"
            )
        else:
            status_message = f"[{position}/{total}] Could not read pages: {Path(file_path).name} ({error})"
        self._append_output_line(status_message)
        self._refresh_files_list()

    def _finalize_file_scan(self, *, token: int, scanned: int, total: int) -> None:
        if token != self._file_scan_token:
            return
        self._set_file_scan_busy(busy=False, message="")
        if total <= 0:
            self._set_file_scan_message()
            return
        self._set_file_scan_message(f"Scanned {scanned}/{total} drawing file(s).")

    def _set_file_scan_message(self, message: str | None = None) -> None:
        if message:
            self.status_text.set(message)
            return
        if not self.files:
            self.status_text.set("No files selected.")
            return
        total = len(self.files)
        self.status_text.set(f"Selected {total} file(s). Scanning metadata...")

    def _choose_overrides_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select sheet overrides JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not selected:
            return
        self.sheet_overrides_path.set(selected)
        self.status_text.set("Overrides file selected.")
        self._save_settings()

    def _set_trade_discovery_busy(self, busy: bool) -> None:
        self.trade_discovery_running = busy
        if self.guided_discover_button is None:
            return
        idle_text = (
            "Find Work Types from Drawings"
            if bool(self.beginner_mode.get())
            else "Analyze Drawings for Trade Options"
        )
        busy_text = "Discovering Work Types..." if bool(self.beginner_mode.get()) else "Discovering Trades..."
        if busy:
            self.guided_discover_button.state(["disabled"])
            self.guided_discover_button.configure(text=busy_text)
        else:
            self.guided_discover_button.state(["!disabled"])
            self.guided_discover_button.configure(text=idle_text)

    def _sync_selected_trades_from_options(self) -> None:
        tokens = [
            trade
            for trade, var in self.trade_option_vars.items()
            if bool(var.get())
        ]
        self.selected_trades.set(",".join(tokens))

    def _populate_trade_options(
        self,
        trades: list[str],
        *,
        preserve_selected: bool = True,
        select_all: bool = False,
    ) -> None:
        if self.guided_trade_options_frame is None:
            return

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in trades:
            token = str(raw).strip()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        normalized.sort()

        existing = set(parse_selected_trade_tokens(self.selected_trades.get()))

        for child in self.guided_trade_options_frame.winfo_children():
            child.destroy()

        ttk.Label(
            self.guided_trade_options_frame,
            text="Selectable Work Types (click to include):",
            style="FormLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")

        self.trade_option_vars = {}
        if not normalized:
            ttk.Label(
                self.guided_trade_options_frame,
                text="No trade options loaded yet. Use Analyze Drawings for Trade Options or Load Trades.",
            ).grid(row=1, column=0, sticky="w", pady=(4, 0))
            return

        options_row = ttk.Frame(self.guided_trade_options_frame)
        options_row.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        for col in range(4):
            options_row.columnconfigure(col, weight=1)

        actions_row = ttk.Frame(self.guided_trade_options_frame)
        actions_row.grid(row=1, column=0, sticky="w", pady=(4, 0))

        def _set_all_trades(enabled: bool) -> None:
            for var in self.trade_option_vars.values():
                var.set(enabled)
            self._sync_selected_trades_from_options()

        for index, trade in enumerate(normalized):
            col = index % 4
            row = index // 4
            initial = select_all or (preserve_selected and trade in existing)
            var = BooleanVar(value=initial)
            self.trade_option_vars[trade] = var
            ttk.Checkbutton(
                options_row,
                text=trade,
                variable=var,
                command=self._sync_selected_trades_from_options,
            ).grid(row=row, column=col, sticky="w", padx=(0, 12), pady=(0, 2))

        ttk.Button(
            actions_row,
            text="Select All",
            command=lambda: _set_all_trades(True),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            actions_row,
            text="Clear All",
            command=lambda: _set_all_trades(False),
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self._sync_selected_trades_from_options()

    def _extract_trade_options_from_job_result(self, payload: dict) -> list[str]:
        result = payload.get("result")
        if not isinstance(result, dict):
            return []
        options: list[str] = []
        trade_scope = result.get("trade_scope")
        if isinstance(trade_scope, dict):
            for key in ("detected_trades", "analyzed_trades"):
                value = trade_scope.get(key)
                if isinstance(value, list):
                    options.extend(str(item).strip() for item in value if str(item).strip())
        sheets = result.get("sheets_detected")
        if isinstance(sheets, list):
            for item in sheets:
                if not isinstance(item, dict):
                    continue
                discipline = str(item.get("discipline", "")).strip()
                if discipline:
                    options.append(discipline)
        deduped: list[str] = []
        seen: set[str] = set()
        for token in options:
            if token and token not in seen:
                seen.add(token)
                deduped.append(token)
        return deduped

    def _discover_trade_options_from_drawings(self) -> None:
        if self.trade_discovery_running:
            self.status_text.set("Trade option discovery is already running.")
            return
        if self.request_task_running:
            self.status_text.set("Another request is running. Wait for it to finish first.")
            return
        if not self.files:
            self.status_text.set("Select drawing PDFs first.")
            self._choose_pdfs()
            if not self.files:
                return
        api_base = self.api_url.get().strip().rstrip("/")
        if not api_base:
            self.status_text.set("API URL is required.")
            return
        self._set_trade_discovery_busy(True)
        self.status_text.set("Analyzing drawings to discover available trades...")
        worker = Thread(
            target=self._discover_trade_options_worker,
            args=(api_base, list(self.files)),
            daemon=True,
        )
        worker.start()

    def _discover_trade_options_worker(self, api_base: str, file_paths: list[str]) -> None:
        try:
            create_payload = self._post_files_to_base(
                api_base=api_base,
                path="/v1/jobs",
                data={"analysis_mode": "auto", "selected_trades": ""},
                file_paths=file_paths,
                timeout=1800,
                progress_callback=lambda message: self.root.after(
                    0, lambda: self._append_output_line(message)
                ),
            )
            job_id = str(create_payload.get("job_id", "")).strip()
            if not job_id:
                raise RuntimeError("Trade discovery job did not return a job_id.")

            payload = self._poll_job_until_terminal(
                api_base=api_base,
                job_id=job_id,
                max_wait_seconds=1800,
                poll_interval_seconds=2,
                progress_callback=lambda message: self.root.after(
                    0, lambda: self._append_output_line(message)
                ),
            )
            status = str(payload.get("status", "")).strip()
            if status != "completed":
                raise RuntimeError(f"Trade discovery job ended with status: {status}")

            trades = self._extract_trade_options_from_job_result(payload)
            if not trades:
                fallback = self._request_json_from_base(
                    "GET",
                    api_base=api_base,
                    path="/v1/meta/trades",
                    timeout=60,
                )
                entries = fallback.get("trades")
                if isinstance(entries, list):
                    trades = [
                        str(entry.get("trade", "")).strip()
                        for entry in entries
                        if isinstance(entry, dict) and str(entry.get("trade", "")).strip()
                    ]
            self.root.after(0, lambda: self._on_discover_trade_options_success(job_id, trades))
        except Exception as exc:
            self.root.after(0, lambda: self._on_discover_trade_options_failure(exc))

    def _on_discover_trade_options_success(self, job_id: str, trades: list[str]) -> None:
        self._set_trade_discovery_busy(False)
        self.current_job_id.set(job_id)
        self._populate_trade_options(trades, preserve_selected=False, select_all=False)
        trade_count = len(self.trade_option_vars)
        self.status_text.set(
            f"Trade options discovered from drawings: {trade_count} option(s). Select and proceed."
        )
        self._save_settings()

    def _on_discover_trade_options_failure(self, exc: Exception) -> None:
        self._set_trade_discovery_busy(False)
        self.status_text.set("Trade discovery failed.")
        self._set_output_text(f"Failed to discover trade options:\n{exc}")

    def _quick_start_run(self) -> None:
        if self.request_task_running:
            self.status_text.set("Another request is already running. Wait for it to finish.")
            return
        if not self.files:
            self._choose_pdfs()
            if not self.files:
                self.status_text.set("Quick start canceled: no drawing files selected.")
                return
        if not self.auto_poll_enabled.get():
            self.auto_poll_enabled.set(True)
        self.status_text.set("Quick start: submitting background job with auto-poll.")
        self._submit_async_job()

    def _start_background_action(
        self,
        *,
        message: str,
        worker: Callable[[], _BGTaskT],
        on_success: Callable[[_BGTaskT], None],
        failure_heading: str,
        failure_status: str,
    ) -> None:
        if self.request_task_running:
            self.status_text.set(_BACKGROUND_BUSY_MESSAGE)
            return

        self._background_action_token += 1
        token = self._background_action_token
        self._set_request_busy(busy=True, message=message)
        self.status_text.set(message)

        def _run() -> None:
            try:
                result = worker()
            except Exception as exc:
                self.root.after(
                    0,
                    lambda: self._finish_background_action_failure(
                        token=token,
                        exc=exc,
                        failure_heading=failure_heading,
                        failure_status=failure_status,
                    ),
                )
                return
            self.root.after(
                0,
                lambda: self._finish_background_action_success(
                    token=token,
                    result=result,
                    on_success=on_success,
                    failure_heading=failure_heading,
                    failure_status=failure_status,
                ),
            )

        Thread(target=_run, daemon=True).start()

    def _finish_background_action_success(
        self,
        *,
        token: int,
        result: _BGTaskT,
        on_success: Callable[[_BGTaskT], None],
        failure_heading: str,
        failure_status: str,
    ) -> None:
        if token != self._background_action_token:
            return
        self._set_request_busy(busy=False)
        try:
            on_success(result)
        except Exception as exc:
            self._finish_background_action_failure(
                token=token,
                exc=exc,
                failure_heading=failure_heading,
                failure_status=failure_status,
            )

    def _finish_background_action_failure(
        self,
        *,
        token: int,
        exc: Exception,
        failure_heading: str,
        failure_status: str,
    ) -> None:
        if token != self._background_action_token:
            return
        self._set_request_busy(busy=False)
        self.runtime_logger.error(f"{failure_heading}: {exc}")
        self.status_text.set(failure_status)
        self._set_output_text(f"{failure_heading}:\n{exc}")

    def _apply_trade_catalog_payload(self, payload: dict, *, update_output: bool) -> None:
        analysis_modes = payload.get("analysis_modes", [])
        trades = payload.get("trades", [])
        if not isinstance(analysis_modes, list) or not isinstance(trades, list):
            raise RuntimeError("Unexpected trade catalog format from API.")

        parsed_modes: list[str] = []
        for item in analysis_modes:
            token = str(item).strip()
            if token:
                parsed_modes.append(token)

        parsed_trades: list[str] = []
        for item in trades:
            if not isinstance(item, dict):
                continue
            token = str(item.get("trade", "")).strip()
            if token:
                parsed_trades.append(token)

        if not parsed_modes or not parsed_trades:
            raise RuntimeError("Trade catalog response did not include usable modes/trades.")

        self.analysis_mode_catalog = parsed_modes
        self.trade_catalog = parsed_trades
        self.analysis_mode_combo["values"] = self.analysis_mode_catalog
        if self.analysis_mode.get().strip() not in self.analysis_mode_catalog:
            self.analysis_mode.set(self.analysis_mode_catalog[0])
        self._populate_trade_options(self.trade_catalog, preserve_selected=True, select_all=False)
        if update_output:
            self._set_output_json(payload)

    def _load_trade_catalog(self) -> None:
        self._start_background_action(
            message="Loading work-type catalog from API...",
            worker=lambda: self._request_json("GET", "/v1/meta/trades", timeout=30),
            on_success=self._on_load_trade_catalog_success,
            failure_heading="Failed to load trade catalog",
            failure_status="Trade catalog load failed.",
        )

    def _on_load_trade_catalog_success(self, payload: dict) -> None:
        self._apply_trade_catalog_payload(payload, update_output=True)
        trade_count = len(self.trade_catalog)
        self.status_text.set(f"Loaded work-type catalog: {trade_count} trade(s).")

    def _refresh_spec_organizations(self) -> None:
        self._start_background_action(
            message="Loading agencies and spec organizations...",
            worker=lambda: self._request_json("GET", "/v1/specs/organizations", timeout=45),
            on_success=self._on_refresh_spec_organizations_success,
            failure_heading="Failed to load spec organizations",
            failure_status="Spec organization load failed.",
        )

    def _on_refresh_spec_organizations_success(self, payload: dict) -> None:
        organizations = payload.get("organizations", [])
        if not isinstance(organizations, list):
            raise RuntimeError("Unexpected organizations payload format.")
        cleaned = [str(item).strip() for item in organizations if isinstance(item, str) and str(item).strip()]
        self.spec_org_catalog = cleaned
        if self.spec_org_combo is not None:
            self.spec_org_combo.configure(values=self.spec_org_catalog)
        if not self.spec_organization.get().strip() and self.spec_org_catalog:
            self.spec_organization.set(self.spec_org_catalog[0])
        self.status_text.set(f"Loaded {len(self.spec_org_catalog)} spec organization(s).")

    def _load_spec_catalog_for_org(self) -> None:
        org = self.spec_organization.get().strip()
        params = [f"public_only={'true' if self.include_public_specs.get() else 'false'}", "limit=200", "offset=0"]
        if org:
            from urllib.parse import quote_plus

            params.append(f"organization={quote_plus(org)}")
        path = f"/v1/specs/catalog?{'&'.join(params)}"
        self._start_background_action(
            message=f"Loading matching specs for '{org or 'all organizations'}'...",
            worker=lambda: self._request_json("GET", path, timeout=60),
            on_success=lambda payload: self._on_load_spec_catalog_success(payload, org=org),
            failure_heading="Failed to load spec catalog",
            failure_status="Spec catalog load failed.",
        )

    def _on_load_spec_catalog_success(self, payload: dict, *, org: str) -> None:
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise RuntimeError("Unexpected spec catalog payload format.")
        self.spec_catalog = [item for item in items if isinstance(item, dict)]
        spec_ids = [
            str(item.get("spec_id", "")).strip()
            for item in self.spec_catalog
            if str(item.get("spec_id", "")).strip()
        ]
        if spec_ids:
            self.spec_profile_ids.set(",".join(spec_ids))
        self._set_output_json(payload)
        self.status_text.set(
            f"Loaded {len(self.spec_catalog)} spec profile(s) for '{org or 'all organizations'}'."
        )
        self._save_settings()

    def _upload_spec_file(self) -> None:
        if self.request_task_running:
            self.status_text.set(_BACKGROUND_BUSY_MESSAGE)
            return
        selected = filedialog.askopenfilename(
            title="Select project spec file",
            filetypes=[
                ("Spec files", "*.pdf *.txt *.md *.csv *.json"),
                ("PDF files", "*.pdf"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            self.status_text.set("Spec upload canceled.")
            return
        org = self.spec_organization.get().strip() or "General"
        title = Path(selected).stem
        is_public = bool(self.publish_uploaded_specs.get())
        tags_csv = "construction,specifications"
        selected_path = Path(selected)

        def _worker() -> dict:
            with selected_path.open("rb") as handle:
                files = [("spec_file", (selected_path.name, handle, "application/octet-stream"))]
                data = {
                    "organization": org,
                    "agency": org,
                    "title": title,
                    "standard_name": "",
                    "project_type": "",
                    "tags_csv": tags_csv,
                    "is_public": "true" if is_public else "false",
                    "notes": "Uploaded from desktop setup window.",
                }
                return self._request_json(
                    "POST",
                    "/v1/specs/upload",
                    data=data,
                    files=files,
                    timeout=300,
                )

        self._start_background_action(
            message=f"Uploading spec file: {selected_path.name}...",
            worker=_worker,
            on_success=self._on_upload_spec_file_success,
            failure_heading="Failed to upload spec file",
            failure_status="Spec upload failed.",
        )

    def _on_upload_spec_file_success(self, payload: dict) -> None:
        item = payload.get("item", {})
        if isinstance(item, dict):
            spec_id = str(item.get("spec_id", "")).strip()
            if spec_id:
                existing_ids = [
                    token.strip()
                    for token in self.spec_profile_ids.get().replace(";", ",").split(",")
                    if token.strip()
                ]
                existing = {token.lower() for token in existing_ids}
                if spec_id.lower() not in existing:
                    existing_ids.append(spec_id)
                    self.spec_profile_ids.set(",".join(existing_ids))
        self._set_output_json(payload)
        scope_text = "public catalog" if bool(self.publish_uploaded_specs.get()) else "private catalog"
        self.status_text.set(f"Spec file uploaded to {scope_text} and added to selected spec IDs.")
        self._save_settings()
        self._refresh_spec_organizations()

    def _search_spec_submittals(self) -> None:
        spec_ids = self.spec_profile_ids.get().strip()
        if not spec_ids:
            self.status_text.set("Select or load at least one spec profile ID first.")
            return
        from urllib.parse import quote_plus

        path = f"/v1/specs/submittals/search?spec_profile_ids={quote_plus(spec_ids)}&max_results=20"
        self._start_background_action(
            message="Searching compliant submittal links...",
            worker=lambda: self._request_json("GET", path, timeout=120),
            on_success=self._on_search_spec_submittals_success,
            failure_heading="Failed to search submittals",
            failure_status="Submittal lookup failed.",
        )

    def _on_search_spec_submittals_success(self, payload: dict) -> None:
        self._set_output_json(payload)
        item_count = len(payload.get("items", [])) if isinstance(payload.get("items"), list) else 0
        self.status_text.set(f"Submittal lookup complete: {item_count} result link(s).")

    def _validate_selected_trades_clicked(self) -> None:
        try:
            normalized_csv = self._validate_scope_inputs_before_submit()
            self.selected_trades.set(normalized_csv)
            self.status_text.set("Trade scope input is valid.")
            self._save_settings()
        except Exception as exc:
            self._set_output_text(f"Trade validation failed:\n{exc}")

    def _run_analysis(self) -> None:
        self.output.delete("1.0", END)
        if self.request_task_running:
            self.status_text.set("Another request is already running. Wait for it to finish.")
            return
        if not self.files:
            self.output.insert(END, "Please select at least one PDF.")
            return

        try:
            data = self._build_request_data()
            api_base = self.api_url.get().strip().rstrip("/")
            if not api_base:
                raise RuntimeError("API URL is required.")
            file_paths = list(self.files)
        except Exception as exc:
            self._set_output_text(f"Failed to start analysis:\n{exc}")
            return

        file_lines = [Path(path).name for path in file_paths]
        self._set_output_text(
            "Starting synchronous analysis:\n"
            f"Files ({len(file_paths)}): {', '.join(file_lines[:10])}"
            + ("\n..." if len(file_lines) > 10 else "")
        )

        self._set_request_busy(
            busy=True,
            message=f"Running analysis on {len(file_paths)} file(s). Large PDFs may take several minutes...",
        )
        self.status_text.set("Uploading drawings and running analysis...")
        worker = Thread(
            target=self._run_analysis_worker,
            args=(api_base, data, file_paths),
            daemon=True,
        )
        worker.start()

    def _submit_async_job(self) -> None:
        self.output.delete("1.0", END)
        if self.request_task_running:
            self.status_text.set("Another request is already running. Wait for it to finish.")
            return
        if not self.files:
            self.output.insert(END, "Please select at least one PDF.")
            return

        try:
            data = self._build_request_data()
            api_base = self.api_url.get().strip().rstrip("/")
            if not api_base:
                raise RuntimeError("API URL is required.")
            file_paths = list(self.files)
        except Exception as exc:
            self._set_output_text(f"Failed to start async job:\n{exc}")
            return

        file_lines = [Path(path).name for path in file_paths]
        self._set_output_text(
            "Submitting background job:\n"
            f"Files ({len(file_paths)}): {', '.join(file_lines[:10])}"
            + ("\n..." if len(file_lines) > 10 else "")
            + "\n\n"
        )

        self._set_request_busy(
            busy=True,
            message=f"Submitting background job for {len(file_paths)} file(s). Uploading large PDFs...",
        )
        self.status_text.set("Uploading files and creating background job...")
        worker = Thread(
            target=self._submit_async_job_worker,
            args=(api_base, data, file_paths),
            daemon=True,
        )
        worker.start()

    def _run_analysis_worker(
        self,
        api_base: str,
        request_data: dict[str, str],
        file_paths: list[str],
    ) -> None:
        try:
            payload = self._post_files_to_base(
                api_base=api_base,
                path="/v1/analyze",
                data=request_data,
                file_paths=file_paths,
                timeout=1800,
                progress_callback=lambda message: self.root.after(0, lambda: self._handle_request_progress_message(message)),
            )
            self.root.after(0, lambda: self._on_run_analysis_success(payload))
        except Exception as exc:
            self.root.after(0, lambda: self._on_run_analysis_failure(exc))

    def _submit_async_job_worker(
        self,
        api_base: str,
        request_data: dict[str, str],
        file_paths: list[str],
    ) -> None:
        try:
            payload = self._post_files_to_base(
                api_base=api_base,
                path="/v1/jobs",
                data=request_data,
                file_paths=file_paths,
                timeout=1800,
                progress_callback=lambda message: self.root.after(0, lambda: self._handle_request_progress_message(message)),
            )
            self.root.after(0, lambda: self._on_submit_async_job_success(payload))
        except Exception as exc:
            self.root.after(0, lambda: self._on_submit_async_job_failure(exc))

    def _on_run_analysis_success(self, payload: dict) -> None:
        self._set_request_busy(busy=False)
        self._set_job_polling(busy=False)
        self._set_run_phase(phase="Completed", percent=100.0)
        self._set_output_json(payload)
        self.status_text.set("Synchronous analysis completed.")

    def _on_run_analysis_failure(self, exc: Exception) -> None:
        self._set_request_busy(busy=False)
        self._set_job_polling(busy=False)
        self._set_run_phase(phase="Failed", percent=100.0)
        self._set_output_text(f"Failed to run analysis:\n{exc}")
        self.status_text.set("Analysis failed.")

    def _on_submit_async_job_success(self, payload: dict) -> None:
        self._set_request_busy(busy=False)
        job_id = str(payload.get("job_id", "")).strip()
        if not job_id:
            self._set_output_text("Failed to submit async job:\nAPI response did not include job_id.")
            self.status_text.set("Async job submission failed.")
            self._set_job_polling(busy=False)
            return
        self.current_job_id.set(job_id)
        self._set_output_json(payload)
        self._save_settings()
        self._autosave_active_project_snapshot()
        self._append_output_line(f"Async job accepted: {job_id}")
        self._set_run_phase(phase="Queued for processing", percent=72.0)
        self._set_job_polling(
            busy=True,
            message=f"Background job accepted ({job_id}). Watching for start of processing...",
        )
        self.status_text.set(f"Async job submitted: {job_id}")
        if not self.auto_poll_enabled.get():
            self.auto_poll_enabled.set(True)
            if self.request_task_running:
                self._append_output_line("Auto poll will start after request completes.")
        if self.auto_poll_enabled.get():
            self._start_auto_poll()

    def _on_submit_async_job_failure(self, exc: Exception) -> None:
        self._set_request_busy(busy=False)
        self._set_job_polling(busy=False)
        self._set_run_phase(phase="Failed", percent=100.0)
        self._set_output_text(f"Failed to submit async job:\n{exc}")
        self.status_text.set("Async job submission failed.")

    def _rerun_job(self) -> None:
        source_job_id = self.current_job_id.get().strip()
        if not source_job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return

        try:
            data = self._build_request_data()
            payload = self._request_json("POST", f"/v1/jobs/{source_job_id}/rerun", data=data, timeout=120)
            new_job_id = str(payload.get("job_id", "")).strip()
            if not new_job_id:
                raise RuntimeError("API response did not include rerun job_id.")
            self.current_job_id.set(new_job_id)
            self._set_output_json(payload)
            self.status_text.set(f"Rerun job submitted: {new_job_id}")
            self._append_output_line(f"Rerun job submitted: {new_job_id}")
            self._save_settings()
            self._autosave_active_project_snapshot()
            if self.auto_poll_enabled.get():
                self._set_job_polling(
                    busy=True,
                    message=f"Watching rerun job {new_job_id}...",
                )
                self._start_auto_poll()
        except Exception as exc:
            self._set_output_text(f"Failed to rerun job:\n{exc}")

    def _rerun_job_with_recommendation(self) -> None:
        source_job_id = self.current_job_id.get().strip()
        if not source_job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return

        try:
            payload = self._request_json(
                "POST",
                f"/v1/jobs/{source_job_id}/rerun-recommended",
                timeout=120,
            )
            new_job_id = str(payload.get("job_id", "")).strip()
            if not new_job_id:
                raise RuntimeError("API response did not include rerun job_id.")
            self.current_job_id.set(new_job_id)
            self._set_output_json(payload)
            mode = payload.get("recommended_mode", "unknown")
            confidence = payload.get("recommendation_confidence", "n/a")
            self.status_text.set(
                f"Recommended rerun submitted: {new_job_id} (mode={mode}, confidence={confidence})"
            )
            self._append_output_line(
                f"Recommended rerun submitted: {new_job_id} (mode={mode}, confidence={confidence})"
            )
            self._save_settings()
            self._autosave_active_project_snapshot()
            if self.auto_poll_enabled.get():
                self._set_job_polling(
                    busy=True,
                    message=f"Watching recommended rerun job {new_job_id}...",
                )
                self._start_auto_poll()
        except Exception as exc:
            self._set_output_text(f"Failed to submit recommended rerun:\n{exc}")

    def _cancel_job(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return

        try:
            payload = self._request_json("POST", f"/v1/jobs/{job_id}/cancel", timeout=60)
            status = str(payload.get("status", "unknown")).strip() or "unknown"
            self._set_output_json(payload)
            self.status_text.set(f"Job {job_id} cancel result: {status}")
            if status == "canceled":
                self._append_output_line(f"Job {job_id} canceled.")
                self._set_job_polling(busy=False)
            if status == "canceled":
                self.auto_poll_enabled.set(False)
                self._save_settings()
                self._autosave_active_project_snapshot()
                self._stop_auto_poll()
            else:
                self._append_output_line(f"Cancel request sent for job {job_id}. New status: {status}")
        except Exception as exc:
            self._set_output_text(f"Failed to cancel job:\n{exc}")

    def _refresh_job(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return
        try:
            payload = self._request_json("GET", f"/v1/jobs/{job_id}", timeout=60)
            status = str(payload.get("status", "")).strip()
            result = payload.get("result")
            if status == "completed" and isinstance(result, dict):
                self._set_output_json(result)
            else:
                self._set_output_json(payload)
            self.status_text.set(f"Job {job_id} status: {status or 'unknown'}")
            phase, percent = self._phase_from_message(self._make_job_poll_message(job_id, status))
            self._set_run_phase(phase=phase, percent=percent)
            self._set_job_polling(
                busy=False if status in _TERMINAL_JOB_STATUSES else self.job_polling,
                message=self._make_job_poll_message(job_id, status),
            )
            if status in _TERMINAL_JOB_STATUSES:
                self._stop_auto_poll()
            self._save_settings()
            if status in _TERMINAL_JOB_STATUSES:
                self._autosave_active_project_snapshot()
        except Exception as exc:
            self._stop_auto_poll()
            self._set_output_text(f"Failed to refresh job:\n{exc}")

    def _load_latest_job(self) -> None:
        try:
            payload = self._request_json("GET", "/v1/jobs?limit=1", timeout=30)
            items = payload.get("items", [])
            if not isinstance(items, list) or not items:
                self._set_output_text("No jobs found.")
                return
            latest = items[0]
            job_id = str(latest.get("job_id", "")).strip()
            if not job_id:
                self._set_output_text("Latest job did not include job_id.")
                return
            self.current_job_id.set(job_id)
            self._set_output_json(latest)
            self.status_text.set(f"Loaded latest job: {job_id}")
            self._save_settings()
            self._autosave_active_project_snapshot()
            if self.auto_poll_enabled.get():
                latest_status = str(latest.get("status", "")).strip()
                if latest_status not in _TERMINAL_JOB_STATUSES:
                    self._set_job_polling(
                        busy=True,
                        message=self._make_job_poll_message(job_id, latest_status),
                    )
                    self._start_auto_poll()
        except Exception as exc:
            self._set_output_text(f"Failed to load latest job:\n{exc}")

    def _show_job_ops_snapshot(self) -> None:
        try:
            payload = self._request_json(
                "GET",
                "/v1/jobs/metrics",
                timeout=30,
                params={"window": 500},
            )
            self._set_output_json(payload)
            counts = payload.get("status_counts", {})
            queued = counts.get("queued", "n/a") if isinstance(counts, dict) else "n/a"
            running = counts.get("running", "n/a") if isinstance(counts, dict) else "n/a"
            failed = counts.get("failed", "n/a") if isinstance(counts, dict) else "n/a"
            canceled = counts.get("canceled", "n/a") if isinstance(counts, dict) else "n/a"
            failure_rate = payload.get("failure_rate", "n/a")
            self.status_text.set(
                "Loaded job ops snapshot: "
                f"queued={queued}, running={running}, failed={failed}, canceled={canceled}, failure_rate={failure_rate}"
            )
        except Exception as exc:
            self._set_output_text(f"Failed to load job ops snapshot:\n{exc}")

    def _evaluate_job_ops_gate(self) -> None:
        try:
            payload = self._request_json(
                "GET",
                "/v1/jobs/metrics/gate",
                timeout=30,
                params={
                    "window": 500,
                    "max_failure_rate": 0.2,
                    "max_active_jobs": 25,
                    "max_missing_scale_rate": 0.4,
                    "max_unmapped_sheet_rate": 0.25,
                    "min_jobs_per_hour_24h": 0.05,
                },
            )
            self._set_output_json(payload)
            passed = payload.get("passed")
            failure_count = len(payload.get("failures", [])) if isinstance(payload.get("failures"), list) else "n/a"
            status = "PASSED" if passed is True else "FAILED"
            self.status_text.set(f"Job ops gate {status}. Failures: {failure_count}")
        except Exception as exc:
            self._set_output_text(f"Failed to evaluate job ops gate:\n{exc}")

    def _prune_jobs_dry_run(self) -> None:
        self._prune_jobs(dry_run=True)

    def _prune_jobs_apply(self) -> None:
        self._prune_jobs(dry_run=False)

    def _prune_jobs(self, *, dry_run: bool) -> None:
        try:
            statuses = self.prune_statuses.get().strip()
            older_than_hours_raw = self.prune_older_than_hours.get().strip()
            limit_raw = self.prune_limit.get().strip()

            older_than_hours: int | None = None
            if older_than_hours_raw:
                older_than_hours = int(older_than_hours_raw)
                if older_than_hours < 1:
                    raise ValueError("Older Than (h) must be at least 1.")

            limit = 100
            if limit_raw:
                limit = int(limit_raw)
            if limit < 1:
                raise ValueError("Limit must be at least 1.")

            params: dict[str, object] = {
                "statuses": statuses,
                "limit": limit,
                "dry_run": dry_run,
                "cleanup_uploads": bool(self.prune_cleanup_uploads.get()),
            }
            if older_than_hours is not None:
                params["older_than_hours"] = older_than_hours

            payload = self._request_json(
                "POST",
                "/v1/jobs/prune",
                timeout=120,
                params=params,
            )
            self._set_output_json(payload)
            total_eligible = payload.get("total_eligible", "n/a")
            total_deleted = payload.get("total_deleted", "n/a")
            mode = "dry-run" if dry_run else "apply"
            self.status_text.set(
                f"Job prune {mode} complete: eligible={total_eligible}, deleted={total_deleted}"
            )
            self._save_settings()
        except Exception as exc:
            self._set_output_text(f"Failed to prune jobs:\n{exc}")

    def _get_trade_recommendation(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return
        try:
            payload = self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/trade-recommendation",
                timeout=30,
            )
            self._set_output_json(payload)
            mode = payload.get("recommended_mode", "unknown")
            trades = payload.get("recommended_trades", [])
            confidence = payload.get("confidence", "n/a")
            trade_count = len(trades) if isinstance(trades, list) else "n/a"
            self.status_text.set(
                f"Trade recommendation: mode={mode}, trades={trade_count}, confidence={confidence}"
            )
        except Exception as exc:
            self._set_output_text(f"Failed to load trade recommendation:\n{exc}")

    def _get_trade_coverage(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return
        try:
            payload = self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/trade-coverage",
                timeout=30,
            )
            self._set_output_json(payload)
            summary = payload.get("summary", {})
            review_count = summary.get("needs_review_count", "n/a") if isinstance(summary, dict) else "n/a"
            total = summary.get("total_trades", "n/a") if isinstance(summary, dict) else "n/a"
            self.status_text.set(
                f"Trade coverage loaded: total_trades={total}, needs_review={review_count}"
            )
        except Exception as exc:
            self._set_output_text(f"Failed to load trade coverage:\n{exc}")

    def _get_readiness_report(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return
        try:
            payload = self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/readiness-report",
                timeout=45,
            )
            self._set_output_json(payload)
            handoff = payload.get("handoff_recommendation", {})
            status = handoff.get("status", "unknown") if isinstance(handoff, dict) else "unknown"
            self.status_text.set(f"Readiness report loaded: handoff_status={status}")
        except Exception as exc:
            self._set_output_text(f"Failed to load readiness report:\n{exc}")

    def _get_review_queue(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return
        try:
            payload = self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/review-queue?low_confidence_threshold=0.75&include_only_flagged=true",
                timeout=60,
            )
            self._set_output_json(payload)
            flagged = payload.get("summary", {}).get("flagged_sheets", "unknown")
            self.status_text.set(f"Review queue loaded. Flagged sheets: {flagged}")
        except Exception as exc:
            self._set_output_text(f"Failed to fetch review queue:\n{exc}")

    def _selected_visual_review_context(self) -> tuple[str, int | None]:
        sheet_id = self.visual_review_sheet_id.get().strip()
        page_index = self._parse_optional_positive_int(self.visual_review_page_index.get().strip())

        tree = self.sheet_navigator_tree
        if tree is not None:
            selection = tree.selection()
            if selection:
                values = tree.item(selection[0], "values")
                if values and len(values) >= 2:
                    selected_page = self._parse_optional_positive_int(str(values[0]).strip())
                    selected_sheet = str(values[1]).strip()
                    if selected_sheet and selected_sheet != "-":
                        sheet_id = selected_sheet
                        page_index = selected_page

        if not sheet_id and isinstance(self.last_result_payload, dict):
            sheets = self.last_result_payload.get("sheets_detected", [])
            if isinstance(sheets, list):
                for row in sheets:
                    if not isinstance(row, dict):
                        continue
                    candidate = str(row.get("sheet_id", "")).strip()
                    if not candidate:
                        continue
                    sheet_id = candidate
                    page_index = self._parse_optional_positive_int(row.get("source_page_index"))
                    break

        if sheet_id:
            self.visual_review_sheet_id.set(sheet_id)
            self.visual_review_page_index.set(str(page_index) if page_index else "")
        return sheet_id, page_index

    def _open_visual_evidence_svg(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
            sheet_id, page_index = self._selected_visual_review_context()
            if not sheet_id:
                raise RuntimeError("Select a sheet in Sheet Navigator or load a completed job first.")
        except Exception as exc:
            self._set_output_text(f"Could not prepare linework view:\n{exc}")
            return

        def worker() -> dict[str, str]:
            params: dict[str, object] = {"sheet_id": sheet_id, "limit": 1000}
            if page_index is not None:
                params["source_page_index"] = page_index
            svg = self._request_text(
                "GET",
                f"/v1/jobs/{job_id}/visual-evidence.svg",
                timeout=60,
                params=params,
            )
            output_dir = self._results_dir()
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_sheet = re.sub(r"[^A-Za-z0-9_.-]+", "_", sheet_id).strip("_") or "sheet"
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            svg_path = output_dir / f"visual-evidence-{job_id[:8]}-{safe_sheet}-{stamp}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            return {
                "job_id": job_id,
                "sheet_id": sheet_id,
                "source_page_index": str(page_index or ""),
                "svg_path": str(svg_path),
            }

        def on_success(payload: dict[str, str]) -> None:
            svg_path = payload["svg_path"]
            self._set_output_json(payload, sync_views=False, prefer_json_tab=True)
            self.status_text.set(f"Linework SVG saved: {svg_path}")
            self._open_path(Path(svg_path))

        self._start_background_action(
            message=f"Building linework view for {sheet_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to open linework view",
            failure_status="Linework view failed.",
        )

    def _open_visual_measurement_page(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
            sheet_id, page_index = self._selected_visual_review_context()
            if not sheet_id:
                raise RuntimeError("Select a sheet in Sheet Navigator or load a completed job first.")
            base = self.api_url.get().strip().rstrip("/")
            if not base:
                raise RuntimeError("API URL is required.")
            params: dict[str, object] = {
                "sheet_id": sheet_id,
                "tenant_id": self.tenant_id.get().strip() or "default",
                "limit": 1000,
            }
            if page_index is not None:
                params["source_page_index"] = page_index
            url = f"{base}/v1/jobs/{job_id}/visual-review?{urlencode(params)}"
            webbrowser.open(url, new=2)
            self.status_text.set(f"Opened visual measurement page for {sheet_id}.")
            self._save_settings()
        except Exception as exc:
            self._set_output_text(f"Could not open visual measurement page:\n{exc}")

    def _show_scale_calibration_window(self) -> None:
        sheet_id, page_index = self._selected_visual_review_context()
        if not sheet_id:
            self.status_text.set("Select a sheet in Sheet Navigator before checking scale.")
            self._set_output_text("Select a sheet in Sheet Navigator or load a completed job first.")
            return

        existing = self.scale_calibration_window
        if existing is not None:
            try:
                if bool(existing.winfo_exists()):
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass

        window = Toplevel(self.root)
        self.scale_calibration_window = window
        window.title("Scale Calibration Preview")
        window.geometry("560x320")
        window.minsize(520, 300)
        window.configure(background=_THEME["surface"])
        window.protocol("WM_DELETE_WINDOW", self._close_scale_calibration_window)

        container = ttk.Frame(window, padding=14)
        container.grid(row=0, column=0, sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="Scale Calibration Preview", style="HeaderTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        ttk.Label(
            container,
            text=(
                "Use one known dimension from the drawing to preview the conversion "
                "from PDF units to feet. This does not change saved job results."
            ),
            style="FormLabel.TLabel",
            wraplength=500,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ttk.Label(container, text="Sheet ID", style="FormLabel.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(container, textvariable=self.visual_review_sheet_id).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=3
        )
        ttk.Label(container, text="Page", style="FormLabel.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Entry(container, textvariable=self.visual_review_page_index).grid(
            row=3, column=1, sticky="ew", padx=(8, 0), pady=3
        )
        ttk.Label(container, text="Measured PDF Units", style="FormLabel.TLabel").grid(
            row=4, column=0, sticky="w"
        )
        ttk.Entry(container, textvariable=self.scale_measured_pdf_units).grid(
            row=4, column=1, sticky="ew", padx=(8, 0), pady=3
        )
        ttk.Label(container, text="Known Length (ft)", style="FormLabel.TLabel").grid(
            row=5, column=0, sticky="w"
        )
        ttk.Entry(container, textvariable=self.scale_known_length_ft).grid(
            row=5, column=1, sticky="ew", padx=(8, 0), pady=3
        )

        action_row = ttk.Frame(container)
        action_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Button(
            action_row,
            text="Preview Calibration",
            style="Primary.TButton",
            command=self._preview_scale_calibration,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            action_row,
            text="Apply to Job Result",
            style="Accent.TButton",
            command=self._apply_scale_calibration,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            action_row,
            text="Close",
            command=self._close_scale_calibration_window,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.visual_review_sheet_id.set(sheet_id)
        self.visual_review_page_index.set(str(page_index) if page_index else "")
        self.status_text.set(f"Scale calibration helper opened for {sheet_id}.")

    def _preview_scale_calibration(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
            sheet_id = self.visual_review_sheet_id.get().strip()
            if not sheet_id:
                raise RuntimeError("Sheet ID is required.")
            measured = self._parse_required_positive_float(
                self.scale_measured_pdf_units.get(),
                field_name="Measured PDF Units",
            )
            known = self._parse_required_positive_float(
                self.scale_known_length_ft.get(),
                field_name="Known Length (ft)",
            )
        except Exception as exc:
            self._set_output_text(f"Could not preview scale calibration:\n{exc}")
            return

        def worker() -> dict:
            return self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/scale-calibration/preview",
                timeout=60,
                params={
                    "sheet_id": sheet_id,
                    "measured_pdf_units": measured,
                    "known_length_ft": known,
                },
            )

        def on_success(payload: dict) -> None:
            self._set_output_json(payload, sync_views=False, prefer_json_tab=True)
            calibration = payload.get("calibration", {})
            preview = payload.get("preview", {})
            factor = calibration.get("feet_per_pdf_unit", "n/a") if isinstance(calibration, dict) else "n/a"
            total_ft = (
                preview.get("calibrated_vector_linework_total_ft", "n/a")
                if isinstance(preview, dict)
                else "n/a"
            )
            self.status_text.set(f"Scale preview loaded: {factor} ft/PDF unit, linework={total_ft} ft.")
            self._save_settings()

        self._start_background_action(
            message=f"Previewing scale calibration for {sheet_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to preview scale calibration",
            failure_status="Scale calibration preview failed.",
        )

    def _apply_scale_calibration(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
            sheet_id = self.visual_review_sheet_id.get().strip()
            if not sheet_id:
                raise RuntimeError("Sheet ID is required.")
            measured = self._parse_required_positive_float(
                self.scale_measured_pdf_units.get(),
                field_name="Measured PDF Units",
            )
            known = self._parse_required_positive_float(
                self.scale_known_length_ft.get(),
                field_name="Known Length (ft)",
            )
        except Exception as exc:
            self._set_output_text(f"Could not apply scale calibration:\n{exc}")
            return

        def worker() -> dict:
            return self._request_json(
                "POST",
                f"/v1/jobs/{job_id}/scale-calibration/apply",
                timeout=90,
                params={
                    "sheet_id": sheet_id,
                    "measured_pdf_units": measured,
                    "known_length_ft": known,
                },
            )

        def on_success(payload: dict) -> None:
            self._set_output_json(payload, sync_views=False, prefer_json_tab=True)
            self.status_text.set(f"Applied manual scale calibration to {sheet_id}. Refresh job to view updated takeoff.")
            self._save_settings()

        self._start_background_action(
            message=f"Applying scale calibration for {sheet_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to apply scale calibration",
            failure_status="Scale calibration apply failed.",
        )

    def _close_scale_calibration_window(self) -> None:
        window = self.scale_calibration_window
        self.scale_calibration_window = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    def _export_overrides_template(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self._set_output_text("Enter a Job ID or click 'Load Latest Job'.")
            return
        include_all_value = "true" if self.include_all_template.get() else "false"
        try:
            payload = self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/sheet-overrides-template?include_all={include_all_value}",
                timeout=60,
            )
            template_rows = payload.get("items", [])
            if not isinstance(template_rows, list):
                raise RuntimeError("Unexpected template format from API.")

            target = filedialog.asksaveasfilename(
                title="Save sheet overrides template",
                initialfile=f"sheet_overrides_template_{job_id[:8]}.json",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if not target:
                self.status_text.set("Template export canceled.")
                return
            Path(target).write_text(json.dumps(template_rows, indent=2), encoding="utf-8")
            self._set_output_json(payload)
            self.status_text.set(f"Overrides template saved: {target}")
        except Exception as exc:
            self._set_output_text(f"Failed to export template:\n{exc}")

    def _export_benchmark_template(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return

        include_unmapped_value = "true" if self.include_unmapped_benchmark.get() else "false"

        try:
            payload = self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/benchmark-template?include_unmapped={include_unmapped_value}",
                timeout=60,
            )
            manifest = payload.get("manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("Unexpected benchmark template format from API.")

            target = filedialog.asksaveasfilename(
                title="Save benchmark manifest template",
                initialfile=f"benchmark_manifest_{job_id[:8]}.json",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if not target:
                self.status_text.set("Benchmark template export canceled.")
                return
            Path(target).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            self._set_output_json(payload)
            self.status_text.set(f"Benchmark template saved: {target}")
        except Exception as exc:
            self._set_output_text(f"Failed to export benchmark template:\n{exc}")

    def _run_baseline_benchmark(self) -> None:
        if self.end_to_end_task_running:
            self.status_text.set("End-to-end benchmark is already running.")
            return
        if self.benchmark_task_running:
            self.status_text.set("Benchmark run already in progress.")
            return
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return

        include_unmapped = bool(self.include_unmapped_benchmark.get())
        api_base = self.api_url.get().strip().rstrip("/")
        if not api_base:
            self._set_output_text("API URL is required.")
            return
        self.benchmark_task_running = True
        self.status_text.set(f"Running baseline benchmark for completed job {job_id}...")

        thread = Thread(
            target=self._run_baseline_benchmark_worker,
            args=(job_id, include_unmapped, api_base),
            daemon=True,
        )
        thread.start()

    def _run_baseline_benchmark_worker(self, job_id: str, include_unmapped: bool, api_base: str) -> None:
        try:
            include_unmapped_value = "true" if include_unmapped else "false"
            payload = self._request_json_from_base(
                "GET",
                api_base=api_base,
                path=f"/v1/jobs/{job_id}/benchmark-template?include_unmapped={include_unmapped_value}",
                timeout=90,
            )
            manifest = payload.get("manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("Benchmark template payload did not include a manifest object.")

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_dir = Path(__file__).resolve().parents[1] / "benchmarks" / "results"
            output_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = output_dir / f"baseline-manifest-{job_id[:8]}-{stamp}.json"
            report_path = output_dir / f"baseline-report-{job_id[:8]}-{stamp}.json"

            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            report = run_benchmark_manifest(
                manifest=manifest,
                manifest_path=manifest_path,
                validate_schema=True,
                schema_path=None,
            )
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

            summary = report.get("summary", {}) if isinstance(report, dict) else {}
            response_payload = {
                "job_id": job_id,
                "include_unmapped": include_unmapped,
                "manifest_path": str(manifest_path),
                "report_path": str(report_path),
                "summary": summary,
            }
            self.root.after(0, lambda: self._on_baseline_benchmark_success(response_payload))
        except Exception as exc:
            self.root.after(0, lambda: self._on_baseline_benchmark_failure(exc))

    def _on_baseline_benchmark_success(self, payload: dict) -> None:
        self.benchmark_task_running = False
        self._set_output_json(payload)
        summary = payload.get("summary", {})
        score = summary.get("overall_score", "n/a") if isinstance(summary, dict) else "n/a"
        self.status_text.set(f"Baseline benchmark complete. Overall score: {score}")

    def _on_baseline_benchmark_failure(self, exc: Exception) -> None:
        self.benchmark_task_running = False
        self._set_output_text(f"Baseline benchmark failed:\n{exc}")
        self.status_text.set("Baseline benchmark failed.")

    def _run_end_to_end_benchmark(self) -> None:
        if self.end_to_end_task_running:
            self.status_text.set("End-to-end benchmark is already running.")
            return
        if self.benchmark_task_running:
            self.status_text.set("Baseline benchmark is already running.")
            return
        if not self.files:
            self._set_output_text("Please select at least one PDF.")
            return

        try:
            api_base = self.api_url.get().strip().rstrip("/")
            if not api_base:
                raise RuntimeError("API URL is required.")
            request_data = self._build_request_data()
            file_paths = list(self.files)
            include_unmapped = bool(self.include_unmapped_benchmark.get())
        except Exception as exc:
            self._set_output_text(f"Failed to start end-to-end benchmark:\n{exc}")
            return

        self.end_to_end_task_running = True
        self.status_text.set("Submitting job and running end-to-end benchmark...")
        self._set_run_phase(phase="Submitting benchmark run", percent=14.0)
        thread = Thread(
            target=self._run_end_to_end_benchmark_worker,
            args=(api_base, request_data, file_paths, include_unmapped),
            daemon=True,
        )
        thread.start()

    def _run_end_to_end_benchmark_worker(
        self,
        api_base: str,
        request_data: dict[str, str],
        file_paths: list[str],
        include_unmapped: bool,
    ) -> None:
        try:
            create_payload = self._post_files_to_base(
                api_base=api_base,
                path="/v1/jobs",
                data=request_data,
                file_paths=file_paths,
                timeout=180,
                progress_callback=lambda message: self.root.after(0, lambda: self._handle_request_progress_message(message)),
            )
            job_id = str(create_payload.get("job_id", "")).strip()
            if not job_id:
                raise RuntimeError("API response did not include job_id.")

            job_payload = self._poll_job_until_terminal(
                api_base=api_base,
                job_id=job_id,
                max_wait_seconds=1200,
                poll_interval_seconds=2,
                progress_callback=lambda message: self.root.after(
                    0, lambda: self._handle_request_progress_message(message)
                ),
            )
            status = str(job_payload.get("status", "")).strip()
            if status != "completed":
                error = job_payload.get("error")
                raise RuntimeError(f"Job ended with status '{status}'. Error: {error}")

            include_unmapped_value = "true" if include_unmapped else "false"
            benchmark_template = self._request_json_from_base(
                "GET",
                api_base=api_base,
                path=f"/v1/jobs/{job_id}/benchmark-template?include_unmapped={include_unmapped_value}",
                timeout=90,
            )
            manifest = benchmark_template.get("manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("Benchmark template payload did not include a manifest object.")

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_dir = Path(__file__).resolve().parents[1] / "benchmarks" / "results"
            output_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = output_dir / f"e2e-manifest-{job_id[:8]}-{stamp}.json"
            report_path = output_dir / f"e2e-report-{job_id[:8]}-{stamp}.json"

            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            report = run_benchmark_manifest(
                manifest=manifest,
                manifest_path=manifest_path,
                validate_schema=True,
                schema_path=None,
            )
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

            summary = report.get("summary", {}) if isinstance(report, dict) else {}
            response_payload = {
                "job_id": job_id,
                "include_unmapped": include_unmapped,
                "manifest_path": str(manifest_path),
                "report_path": str(report_path),
                "summary": summary,
            }
            self.root.after(0, lambda: self._on_end_to_end_benchmark_success(job_id, response_payload))
        except Exception as exc:
            self.root.after(0, lambda: self._on_end_to_end_benchmark_failure(exc))

    def _on_end_to_end_benchmark_success(self, job_id: str, payload: dict) -> None:
        self.end_to_end_task_running = False
        self.current_job_id.set(job_id)
        self._save_settings()
        self._autosave_active_project_snapshot()
        self._set_output_json(payload)
        self._set_run_phase(phase="Benchmark completed", percent=100.0)
        summary = payload.get("summary", {})
        score = summary.get("overall_score", "n/a") if isinstance(summary, dict) else "n/a"
        self.status_text.set(f"End-to-end benchmark complete. Overall score: {score}")

    def _on_end_to_end_benchmark_failure(self, exc: Exception) -> None:
        self.end_to_end_task_running = False
        self._set_run_phase(phase="Benchmark failed", percent=100.0)
        self._set_output_text(f"End-to-end benchmark failed:\n{exc}")
        self.status_text.set("End-to-end benchmark failed.")

    def _toggle_auto_poll(self) -> None:
        if self.auto_poll_enabled.get():
            self._start_auto_poll()
        else:
            self._stop_auto_poll()
        self._save_settings()

    def _start_auto_poll(self) -> None:
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self.status_text.set("Auto poll not started: no current job ID.")
            self.auto_poll_enabled.set(False)
            self._set_job_polling(busy=False)
            return
        if self.auto_poll_handle is not None:
            return
        self._auto_poll_cycle = 0
        self.status_text.set(f"Auto polling job {job_id} every {self.auto_poll_interval_ms // 1000}s.")
        if not self.job_polling:
            self._set_job_polling(
                busy=True,
                message=f"Auto-polling job {job_id} (every {self.auto_poll_interval_ms // 1000}s)...",
            )
        self.auto_poll_handle = self.root.after(self.auto_poll_interval_ms, self._auto_poll_tick)

    def _stop_auto_poll(self) -> None:
        if self.auto_poll_handle is not None:
            self.root.after_cancel(self.auto_poll_handle)
            self.auto_poll_handle = None
        self._set_job_polling(busy=False)
        self.auto_poll_enabled.set(False)

    def _auto_poll_tick(self) -> None:
        self.auto_poll_handle = None
        if not self.auto_poll_enabled.get():
            self._set_job_polling(busy=False)
            return
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self.auto_poll_enabled.set(False)
            self._set_job_polling(busy=False)
            self.status_text.set("Auto poll stopped: no current job ID.")
            return
        self._auto_poll_cycle += 1

        try:
            payload = self._request_json("GET", f"/v1/jobs/{job_id}", timeout=30)
            status = str(payload.get("status", "")).strip()
            result = payload.get("result")
            if status == "completed" and isinstance(result, dict):
                self._set_output_json(result)
                self.status_text.set(f"Job {job_id} completed.")
                self._set_run_phase(phase="Completed", percent=100.0)
                self._set_job_polling(busy=False)
                self.auto_poll_enabled.set(False)
                self._save_settings()
                self._autosave_active_project_snapshot()
                self._stop_auto_poll()
                return
            if status in {"failed", "canceled"}:
                self._set_output_json(payload)
                self.status_text.set(f"Job {job_id} {status}.")
                self._set_run_phase(phase=status.title(), percent=100.0)
                self._set_job_polling(busy=False)
                self.auto_poll_enabled.set(False)
                self._save_settings()
                self._autosave_active_project_snapshot()
                self._stop_auto_poll()
                return
            self._set_job_polling(
                busy=True,
                message=self._make_job_poll_message(job_id, status),
            )
            self._set_output_json(payload)
            self.status_text.set(f"Job {job_id} status: {status or 'unknown'} (auto polling)")
        except Exception as exc:
            self.status_text.set(f"Auto poll error: {exc}")
            self.auto_poll_enabled.set(False)
            self._set_job_polling(busy=False)
            self._stop_auto_poll()
            return

        self.auto_poll_handle = self.root.after(self.auto_poll_interval_ms, self._auto_poll_tick)

    def _refresh_trade_catalog_from_api(self, *, update_output: bool) -> dict:
        payload = self._request_json("GET", "/v1/meta/trades", timeout=30)
        self._apply_trade_catalog_payload(payload, update_output=update_output)
        return payload

    def _validate_scope_inputs_before_submit(self) -> str:
        if not self.trade_catalog:
            try:
                self._refresh_trade_catalog_from_api(update_output=False)
            except Exception:
                # Continue without catalog-backed unknown-trade checks when catalog is unreachable.
                pass

        tokens = validate_selected_trade_scope(
            analysis_mode=self.analysis_mode.get(),
            selected_trades_csv=self.selected_trades.get(),
            valid_trades=self.trade_catalog if self.trade_catalog else None,
        )
        return ",".join(tokens)

    def _build_request_data(self) -> dict[str, str]:
        selected_trades_csv = self._validate_scope_inputs_before_submit()
        data = {
            "analysis_mode": self.analysis_mode.get(),
            "selected_trades": selected_trades_csv,
        }
        spec_profile_ids = self.spec_profile_ids.get().strip()
        spec_organization = self.spec_organization.get().strip()
        data["include_public_specs"] = "true" if bool(self.include_public_specs.get()) else "false"
        if spec_profile_ids:
            data["spec_profile_ids"] = spec_profile_ids
        if spec_organization:
            data["spec_organization"] = spec_organization
        notes = self.notes.get().strip()
        if notes:
            data["notes"] = notes
        overrides_path_text = self.sheet_overrides_path.get().strip()
        if not overrides_path_text:
            return data

        overrides_path = Path(overrides_path_text)
        if not overrides_path.exists():
            raise RuntimeError(f"Overrides file not found: {overrides_path}")
        raw = overrides_path.read_text(encoding="utf-8")
        try:
            parsed = parse_sheet_overrides_json(raw)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if parsed is None:
            raise RuntimeError("Overrides JSON is empty.")
        data["sheet_overrides_json"] = json.dumps(parsed, ensure_ascii=True)
        return data

    def _post_files(self, path: str, *, data: dict[str, str], timeout: int) -> dict:
        files = []
        handles = []
        try:
            for file_path in self.files:
                handle = open(file_path, "rb")
                handles.append(handle)
                files.append(("files", (Path(file_path).name, handle, "application/pdf")))
            return self._request_json("POST", path, data=data, files=files, timeout=timeout)
        finally:
            for handle in handles:
                handle.close()

    def _post_files_to_base(
        self,
        *,
        api_base: str,
        path: str,
        data: dict[str, str],
        file_paths: list[str],
        timeout: int,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        files = []
        handles = []
        seen_paths = set[str]()
        if not file_paths:
            raise RuntimeError("No files were provided for upload.")
        if progress_callback is not None:
            total = len(file_paths)
            progress_callback(f"Preparing {total} drawing file(s) for upload...")
        try:
            for file_path in file_paths:
                normalized_path = str(file_path).strip()
                if not normalized_path:
                    raise RuntimeError("One or more PDF paths are empty.")
                if normalized_path in seen_paths:
                    continue
                seen_paths.add(normalized_path)
                path_obj = Path(normalized_path)
                if not path_obj.exists():
                    raise RuntimeError(f"Selected file not found: {normalized_path}")
                if not path_obj.is_file():
                    raise RuntimeError(f"Selected path is not a file: {normalized_path}")
                size = path_obj.stat().st_size
                if size <= 0:
                    raise RuntimeError(f"Selected file is empty: {normalized_path}")
                if progress_callback is not None:
                    progress_callback(f"Attaching {path_obj.name} ({self._format_size_label(size)}).")
                handle = open(path_obj, "rb")
                handles.append(handle)
                files.append(("files", (path_obj.name, handle, "application/pdf")))
            if not files:
                raise RuntimeError("No valid PDF files were selected after validation.")
            if progress_callback is not None:
                progress_callback(f"Uploading {len(files)} file(s) to {path} ...")
            return self._request_json_from_base(
                "POST",
                api_base=api_base,
                path=path,
                data=data,
                files=files,
                timeout=timeout,
            )
        finally:
            if progress_callback is not None and handles:
                progress_callback("Upload complete, waiting for API response...")
            for handle in handles:
                handle.close()

    def _poll_job_until_terminal(
        self,
        *,
        api_base: str,
        job_id: str,
        max_wait_seconds: int,
        poll_interval_seconds: int,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        deadline = time.time() + max(1, max_wait_seconds)
        last_payload: dict = {}
        while time.time() < deadline:
            payload = self._request_json_from_base(
                "GET",
                api_base=api_base,
                path=f"/v1/jobs/{job_id}",
                timeout=30,
            )
            last_payload = payload
            status = str(payload.get("status", "")).strip()
            if status in _TERMINAL_JOB_STATUSES:
                return payload
            if progress_callback is not None:
                progress_callback(self._make_job_poll_message(job_id, status))
            time.sleep(max(1, poll_interval_seconds))
        raise RuntimeError(
            f"Timed out waiting for job {job_id}. Last status: {last_payload.get('status', 'unknown')}"
        )

    def _request_json(self, method: str, path: str, *, timeout: int = 60, **kwargs: object) -> dict:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            raise RuntimeError("API URL is required.")
        return self._request_json_from_base(method, api_base=base, path=path, timeout=timeout, **kwargs)

    def _request_text(self, method: str, path: str, *, timeout: int = 60, **kwargs: object) -> str:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            raise RuntimeError("API URL is required.")
        url = f"{base}{path}"
        kwargs = dict(kwargs)
        headers = self._request_headers(extra=kwargs.get("headers"))
        kwargs["headers"] = headers
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            auto_started = self._ensure_local_api_running(base)
            if auto_started:
                response = requests.request(method, url, timeout=timeout, **kwargs)
            else:
                raise RuntimeError(
                    "Could not connect to API. If using local mode, click 'Start Local API'."
                ) from exc
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code}: {response.text}")
        return response.text

    def _request_bytes(self, method: str, path: str, *, timeout: int = 60, **kwargs: object) -> bytes:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            raise RuntimeError("API URL is required.")
        url = f"{base}{path}"
        kwargs = dict(kwargs)
        headers = self._request_headers(extra=kwargs.get("headers"))
        kwargs["headers"] = headers
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            auto_started = self._ensure_local_api_running(base)
            if auto_started:
                response = requests.request(method, url, timeout=timeout, **kwargs)
            else:
                raise RuntimeError(
                    "Could not connect to API. If using local mode, click 'Start Local API'."
                ) from exc
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code}: {response.text}")
        return response.content

    def _request_json_from_base(
        self,
        method: str,
        *,
        api_base: str,
        path: str,
        timeout: int = 60,
        **kwargs: object,
    ) -> dict:
        base = api_base.strip().rstrip("/")
        if not base:
            raise RuntimeError("API URL is required.")
        url = f"{base}{path}"
        kwargs = dict(kwargs)
        headers = self._request_headers(extra=kwargs.get("headers"))
        kwargs["headers"] = headers
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            auto_started = self._ensure_local_api_running(base)
            if auto_started:
                response = requests.request(method, url, timeout=timeout, **kwargs)
            else:
                raise RuntimeError(
                    "Could not connect to API. If using local mode, click 'Start Local API'."
                ) from exc
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code}: {response.text}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Response JSON was not an object.")
        return payload

    def _clear_tree_rows(self, tree: ttk.Treeview | None) -> None:
        if tree is None:
            return
        try:
            tree.delete(*tree.get_children())
        except Exception:
            return

    def _extract_result_payload(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        if "sheets_detected" in payload and "quantity_takeoff" in payload:
            return payload
        return {}

    def _format_metric_dict(self, values: object) -> str:
        if not isinstance(values, dict) or not values:
            return "-"
        segments: list[str] = []
        for key in sorted(values.keys(), key=lambda item: str(item).casefold()):
            value = values.get(key)
            if isinstance(value, (int, float)):
                segments.append(f"{key}:{value:g}")
            else:
                segments.append(f"{key}:{value}")
        return ", ".join(segments)

    def _populate_summary_tree(self, result: dict) -> None:
        tree = self.summary_result_tree
        self._clear_tree_rows(tree)
        if tree is None:
            return

        quantity_takeoff = result.get("quantity_takeoff")
        if not isinstance(quantity_takeoff, dict):
            self.summary_banner_text.set("No quantity takeoff found in the current result.")
            return

        by_trade = quantity_takeoff.get("by_trade")
        trade_rows = by_trade if isinstance(by_trade, dict) else {}
        sheets = result.get("sheets_detected")
        sheet_count = len(sheets) if isinstance(sheets, list) else 0
        unknown_symbols = len(result.get("legend_and_symbols", {}).get("unknown_symbols", [])) if isinstance(result.get("legend_and_symbols"), dict) else 0
        self.summary_banner_text.set(
            f"Sheets: {sheet_count} | Work types: {len(trade_rows) if trade_rows else 0} | Unknown symbols: {unknown_symbols}"
        )

        if not trade_rows:
            counts_text = self._format_metric_dict(quantity_takeoff.get("counts"))
            tree.insert(
                "",
                END,
                values=(
                    "All",
                    self._format_metric_dict(quantity_takeoff.get("linear")),
                    self._format_metric_dict(quantity_takeoff.get("area")),
                    self._format_metric_dict(quantity_takeoff.get("volume")),
                    counts_text,
                    "Review",
                ),
            )
            return

        for trade_name in sorted(trade_rows.keys(), key=lambda value: str(value).casefold()):
            trade_data = trade_rows.get(trade_name, {})
            if not isinstance(trade_data, dict):
                continue
            counts = trade_data.get("counts")
            count_total = 0.0
            if isinstance(counts, dict):
                for value in counts.values():
                    if isinstance(value, (int, float)):
                        count_total += float(value)
            review_status = "Ready" if count_total > 0 else "Review"
            tree.insert(
                "",
                END,
                values=(
                    str(trade_name),
                    self._format_metric_dict(trade_data.get("linear")),
                    self._format_metric_dict(trade_data.get("area")),
                    self._format_metric_dict(trade_data.get("volume")),
                    self._format_metric_dict(counts),
                    review_status,
                ),
            )

    def _populate_reviewed_line_items_tree(self, items: object) -> None:
        self.reviewed_line_items_all = [
            raw_item for raw_item in items if isinstance(raw_item, dict)
        ] if isinstance(items, list) else []
        self.reviewed_line_items_active_rollup_filter = None
        self._refresh_reviewed_line_item_filter_options()
        self._render_reviewed_line_items_tree()

    def _refresh_reviewed_line_item_filter_options(self) -> None:
        options = reviewed_takeoff_trade_filter_options(self.reviewed_line_items_all)
        combo = self.reviewed_line_items_filter_combo
        if combo is not None:
            combo.configure(values=options)
        current = self.reviewed_line_items_filter_trade.get().strip()
        if current not in options:
            self.reviewed_line_items_filter_trade.set(_REVIEWED_LINE_ITEMS_ALL_FILTER)
            current = _REVIEWED_LINE_ITEMS_ALL_FILTER

        item_options = reviewed_takeoff_item_filter_options(self.reviewed_line_items_all, current)
        item_combo = self.reviewed_line_items_item_filter_combo
        if item_combo is not None:
            item_combo.configure(values=item_options)
        current_item = self.reviewed_line_items_filter_item.get().strip()
        if current_item not in item_options:
            self.reviewed_line_items_filter_item.set(_REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER)

    def _render_reviewed_line_items_tree(self) -> None:
        tree = self.reviewed_line_items_tree
        self.reviewed_line_items_by_tree_id = {}
        self._clear_tree_rows(tree)
        if tree is None:
            return

        if not self.reviewed_line_items_all:
            self.reviewed_line_items_banner_text.set(
                "No reviewed takeoff line items yet. Use Sheet Navigator > Measure Scale Visually to add field-reviewed measurements."
            )
            self._populate_reviewed_line_items_rollup_tree([], "", "")
            return

        selected_trade = self.reviewed_line_items_filter_trade.get().strip()
        selected_item = self.reviewed_line_items_filter_item.get().strip()
        filtered_items = self._filtered_reviewed_line_items()
        if not filtered_items:
            item_suffix = ""
            if selected_item and selected_item != _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER:
                item_suffix = f" and item '{selected_item}'"
            self.reviewed_line_items_banner_text.set(
                f"No reviewed takeoff line items match work type '{selected_trade}'{item_suffix}."
            )
            self._populate_reviewed_line_items_rollup_tree([], selected_trade, selected_item)
            return

        inserted = 0
        for raw_item in filtered_items[:500]:
            if not isinstance(raw_item, dict):
                continue
            tree_item_id = tree.insert("", END, values=reviewed_takeoff_line_item_values(raw_item))
            self.reviewed_line_items_by_tree_id[tree_item_id] = raw_item
            inserted += 1

        overflow_count = len(filtered_items) - 500
        overflow_text = f" | {overflow_count} more not shown" if overflow_count > 0 else ""
        filter_text = ""
        if selected_trade and selected_trade != _REVIEWED_LINE_ITEMS_ALL_FILTER:
            filter_text = f" | filtered to {selected_trade}"
        if selected_item and selected_item != _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER:
            filter_text += f" / {selected_item}"
        exact_rollup = self.reviewed_line_items_active_rollup_filter
        if isinstance(exact_rollup, dict):
            unit = str(exact_rollup.get("unit", "")).strip() or "unit"
            cost_code = str(exact_rollup.get("cost_code", "")).strip() or "-"
            filter_text += f" | exact rollup {unit}, cost code {cost_code}"
        totals_text = format_reviewed_takeoff_line_item_totals(
            reviewed_takeoff_line_item_totals_by_unit(filtered_items)
        )
        self.reviewed_line_items_banner_text.set(
            f"Reviewed takeoff line items: {inserted} shown of {len(self.reviewed_line_items_all)} total{filter_text} | totals: {totals_text}{overflow_text}."
        )
        self._populate_reviewed_line_items_rollup_tree(filtered_items, selected_trade, selected_item)

    def _populate_reviewed_line_items_rollup_tree(
        self,
        items: list[dict[str, Any]],
        selected_trade: str,
        selected_item: str,
    ) -> None:
        tree = self.reviewed_line_items_rollup_tree
        self.reviewed_line_items_rollup_by_tree_id = {}
        self._clear_tree_rows(tree)
        if tree is None:
            return

        rollups = reviewed_takeoff_line_item_rollups(items)
        if not rollups:
            self.reviewed_rollup_banner_text.set(
                "No grouped reviewed takeoff totals match the current filters."
            )
            return

        for row in rollups:
            tree_item_id = tree.insert("", END, values=reviewed_takeoff_line_item_rollup_values(row))
            self.reviewed_line_items_rollup_by_tree_id[tree_item_id] = row

        totals_text = format_reviewed_takeoff_line_item_totals(
            reviewed_takeoff_line_item_totals_by_unit(items)
        )
        filter_parts: list[str] = []
        if selected_trade and selected_trade != _REVIEWED_LINE_ITEMS_ALL_FILTER:
            filter_parts.append(selected_trade)
        if selected_item and selected_item != _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER:
            filter_parts.append(selected_item)
        filter_text = f" Filter: {' / '.join(filter_parts)}." if filter_parts else ""
        self.reviewed_rollup_banner_text.set(
            f"Grouped reviewed takeoff totals: {len(rollups)} row(s), {len(items)} measurement(s), totals: {totals_text}.{filter_text}"
        )

    def _selected_reviewed_rollup_row(self) -> dict[str, Any] | None:
        tree = self.reviewed_line_items_rollup_tree
        if tree is None:
            return None
        selection = tree.selection()
        if not selection:
            return None
        row = self.reviewed_line_items_rollup_by_tree_id.get(selection[0])
        return row if isinstance(row, dict) else None

    def _on_reviewed_rollup_select(self, _event: object = None) -> None:
        row = self._selected_reviewed_rollup_row()
        if not row:
            return
        trade, item = reviewed_takeoff_line_item_rollup_filter_values(row)
        unit = str(row.get("unit", "")).strip() or "unit"
        quantity = reviewed_takeoff_line_item_rollup_values(row)[2]
        self.status_text.set(
            f"Selected grouped total: {quantity} {unit} for {trade} / {item}. Double-click or use Show Selected Detail."
        )

    def _show_selected_reviewed_rollup_detail(self, _event: object = None) -> None:
        row = self._selected_reviewed_rollup_row()
        if not row:
            self._set_output_text(
                "Select a grouped total in the Takeoff Rollup tab first, then click Show Selected Detail."
            )
            return

        trade, item = reviewed_takeoff_line_item_rollup_filter_values(row)
        self.reviewed_line_items_filter_trade.set(trade)
        item_options = reviewed_takeoff_item_filter_options(self.reviewed_line_items_all, trade)
        self.reviewed_line_items_filter_item.set(
            item if item in item_options else _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER
        )
        self.reviewed_line_items_active_rollup_filter = row
        self._refresh_reviewed_line_item_filter_options()
        self._render_reviewed_line_items_tree()
        if self.results_notebook is not None:
            self.results_notebook.select(0)
        shown_count = len(self._filtered_reviewed_line_items())
        self.status_text.set(f"Showing {shown_count} detail line(s) for grouped total: {trade} / {item}.")

    def _on_reviewed_line_item_filter_change(self, _event: object = None) -> None:
        self.reviewed_line_items_active_rollup_filter = None
        self._refresh_reviewed_line_item_filter_options()
        self._render_reviewed_line_items_tree()

    def _clear_reviewed_line_item_filter(self) -> None:
        self.reviewed_line_items_active_rollup_filter = None
        self.reviewed_line_items_filter_trade.set(_REVIEWED_LINE_ITEMS_ALL_FILTER)
        self.reviewed_line_items_filter_item.set(_REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER)
        self._refresh_reviewed_line_item_filter_options()
        self._render_reviewed_line_items_tree()

    def _filtered_reviewed_line_items(self) -> list[dict[str, Any]]:
        items = filter_reviewed_takeoff_line_items(
            self.reviewed_line_items_all,
            self.reviewed_line_items_filter_trade.get(),
            self.reviewed_line_items_filter_item.get(),
        )
        exact_rollup = self.reviewed_line_items_active_rollup_filter
        if not isinstance(exact_rollup, dict):
            return items
        return [
            raw_item
            for raw_item in items
            if reviewed_takeoff_line_item_matches_rollup(raw_item, exact_rollup)
        ]

    def _save_filtered_reviewed_line_items_csv(self) -> None:
        items = self._filtered_reviewed_line_items()
        if not items:
            self._set_output_text(
                "No reviewed takeoff line items match the current filter. Load a completed job or choose a different Work Type."
            )
            return

        selected_trade = self.reviewed_line_items_filter_trade.get().strip() or _REVIEWED_LINE_ITEMS_ALL_FILTER
        selected_item = self.reviewed_line_items_filter_item.get().strip() or _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER
        safe_trade = re.sub(r"[^A-Za-z0-9_.-]+", "_", selected_trade).strip("_") or "all"
        safe_item = re.sub(r"[^A-Za-z0-9_.-]+", "_", selected_item).strip("_") or "all"
        job_id = self.current_job_id.get().strip() or "job"
        initial_name = f"reviewed-takeoff-lines-{job_id[:8]}-{safe_trade}-{safe_item}.csv"
        path = filedialog.asksaveasfilename(
            title="Save reviewed takeoff line items",
            defaultextension=".csv",
            initialdir=str(self._results_dir()),
            initialfile=initial_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            self.status_text.set("Reviewed takeoff CSV export canceled.")
            return

        csv_rows = reviewed_takeoff_line_item_csv_rows(items)
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=_REVIEWED_LINE_ITEM_CSV_FIELDS)
                writer.writeheader()
                writer.writerows(csv_rows)
        except Exception as exc:
            self._set_output_text(f"Failed to save reviewed takeoff line CSV:\n{exc}")
            return

        totals_text = format_reviewed_takeoff_line_item_totals(
            reviewed_takeoff_line_item_totals_by_unit(items)
        )
        self.status_text.set(f"Saved {len(csv_rows)} reviewed takeoff line(s): {path}")
        self._set_output_text(
            f"Saved reviewed takeoff CSV:\n{path}\n\nRows: {len(csv_rows)}\nTotals: {totals_text}"
        )

    def _save_reviewed_line_items_rollup_csv(self) -> None:
        items = self._filtered_reviewed_line_items()
        csv_rows = reviewed_takeoff_line_item_rollup_csv_rows(items)
        if not csv_rows:
            self._set_output_text(
                "No grouped reviewed takeoff totals match the current filters. Load a completed job or choose a different Work Type/Item."
            )
            return

        selected_trade = self.reviewed_line_items_filter_trade.get().strip() or _REVIEWED_LINE_ITEMS_ALL_FILTER
        selected_item = self.reviewed_line_items_filter_item.get().strip() or _REVIEWED_LINE_ITEMS_ALL_ITEM_FILTER
        safe_trade = re.sub(r"[^A-Za-z0-9_.-]+", "_", selected_trade).strip("_") or "all"
        safe_item = re.sub(r"[^A-Za-z0-9_.-]+", "_", selected_item).strip("_") or "all"
        job_id = self.current_job_id.get().strip() or "job"
        initial_name = f"reviewed-takeoff-rollup-{job_id[:8]}-{safe_trade}-{safe_item}.csv"
        path = filedialog.asksaveasfilename(
            title="Save reviewed takeoff rollup",
            defaultextension=".csv",
            initialdir=str(self._results_dir()),
            initialfile=initial_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            self.status_text.set("Reviewed takeoff rollup CSV export canceled.")
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=_REVIEWED_LINE_ITEM_ROLLUP_CSV_FIELDS)
                writer.writeheader()
                writer.writerows(csv_rows)
        except Exception as exc:
            self._set_output_text(f"Failed to save reviewed takeoff rollup CSV:\n{exc}")
            return

        totals_text = format_reviewed_takeoff_line_item_totals(
            reviewed_takeoff_line_item_totals_by_unit(items)
        )
        self.status_text.set(f"Saved {len(csv_rows)} reviewed takeoff rollup row(s): {path}")
        self._set_output_text(
            f"Saved reviewed takeoff rollup CSV:\n{path}\n\nRows: {len(csv_rows)}\nTotals: {totals_text}"
        )

    def _selected_reviewed_line_item(self) -> dict[str, Any] | None:
        tree = self.reviewed_line_items_tree
        if tree is None:
            return None
        selection = tree.selection()
        if not selection:
            return None
        raw_item = self.reviewed_line_items_by_tree_id.get(selection[0])
        return raw_item if isinstance(raw_item, dict) else None

    def _on_reviewed_line_item_select(self, _event: object = None) -> None:
        raw_item = self._selected_reviewed_line_item()
        if not raw_item:
            return
        sheet_id, page_index, source_id = reviewed_takeoff_line_item_source(raw_item)
        if sheet_id:
            self.visual_review_sheet_id.set(sheet_id)
        if page_index is not None:
            self.visual_review_page_index.set(str(page_index))
        source_text = f"{sheet_id or 'sheet unknown'}"
        if page_index is not None:
            source_text += f" page {page_index}"
        if source_id:
            source_text += f" measurement {source_id}"
        self.status_text.set(f"Selected reviewed takeoff source: {source_text}.")

    def _open_selected_reviewed_line_source(self, _event: object = None) -> str:
        raw_item = self._selected_reviewed_line_item()
        if not raw_item:
            self._set_output_text("Select a reviewed takeoff line item first, then click Open Selected Line Source.")
            return "break"

        try:
            job_id = self._resolve_completed_job_id()
            sheet_id, page_index, source_id = reviewed_takeoff_line_item_source(raw_item)
            if not sheet_id:
                raise RuntimeError("The selected line item does not include a source sheet.")
            base = self.api_url.get().strip().rstrip("/")
            if not base:
                raise RuntimeError("API URL is required.")

            self.visual_review_sheet_id.set(sheet_id)
            self.visual_review_page_index.set(str(page_index) if page_index else "")
            params: dict[str, object] = {
                "sheet_id": sheet_id,
                "tenant_id": self.tenant_id.get().strip() or "default",
                "limit": 1000,
            }
            if page_index is not None:
                params["source_page_index"] = page_index
            url = f"{base}/v1/jobs/{job_id}/visual-review?{urlencode(params)}"
            webbrowser.open(url, new=2)
            source_suffix = f" measurement {source_id}" if source_id else ""
            self.status_text.set(f"Opened source review for {sheet_id}{source_suffix}.")
            self._save_settings()
        except Exception as exc:
            self._set_output_text(f"Could not open selected line source:\n{exc}")
        return "break"

    def _populate_sheet_navigator(self, payload: dict, result: dict) -> None:
        tree = self.sheet_navigator_tree
        self._clear_tree_rows(tree)
        if tree is None:
            return
        sheets = result.get("sheets_detected")
        if not isinstance(sheets, list):
            self.sheet_banner_text.set("No sheet metadata in the current result.")
            return

        flagged_sheets: set[str] = set()
        review_queue = payload.get("review_queue")
        if isinstance(review_queue, dict):
            items = review_queue.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        sid = str(item.get("sheet_id", "")).strip()
                        if sid:
                            flagged_sheets.add(sid)
        if not flagged_sheets:
            review_items = payload.get("items")
            if isinstance(review_items, list):
                for item in review_items:
                    if isinstance(item, dict):
                        sid = str(item.get("sheet_id", "")).strip()
                        if sid:
                            flagged_sheets.add(sid)

        for entry in sheets:
            if not isinstance(entry, dict):
                continue
            sheet_id = str(entry.get("sheet_id", "")).strip()
            title = str(entry.get("title", "")).strip()
            discipline = str(entry.get("discipline", "")).strip() or "-"
            sheet_type = str(entry.get("sheet_type", "")).strip() or "-"
            source_page_index = entry.get("source_page_index")
            page_display = str(source_page_index) if isinstance(source_page_index, int) else "-"
            confidence_value = entry.get("confidence")
            confidence = f"{float(confidence_value):.2f}" if isinstance(confidence_value, (int, float)) else "-"
            flags: list[str] = []
            if sheet_id.startswith("UNMAPPED_"):
                flags.append("UNMAPPED")
            if sheet_id in flagged_sheets:
                flags.append("REVIEW")
            if confidence != "-" and isinstance(confidence_value, (int, float)) and confidence_value < 0.70:
                flags.append("LOW_CONF")
            flags_text = ",".join(flags) if flags else "-"
            tree.insert(
                "",
                END,
                values=(
                    page_display,
                    sheet_id or title or "-",
                    discipline,
                    sheet_type,
                    confidence,
                    flags_text,
                ),
            )

        self.sheet_banner_text.set(
            f"Loaded {len(sheets)} sheet entries. Select a row to filter raw JSON by sheet id."
        )

    def _sync_visual_result_views(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        result = self._extract_result_payload(payload)
        if result:
            self.latest_payload = payload
            self.last_result_payload = result
            self._populate_summary_tree(result)
            quantity_takeoff = result.get("quantity_takeoff")
            line_items = quantity_takeoff.get("line_items") if isinstance(quantity_takeoff, dict) else []
            self._populate_reviewed_line_items_tree(line_items)
            self._populate_sheet_navigator(payload, result)
            return
        review_items = payload.get("items")
        if isinstance(review_items, list) and self.last_result_payload:
            self._populate_sheet_navigator({"review_queue": payload}, self.last_result_payload)
            return
        self._clear_tree_rows(self.summary_result_tree)
        self.reviewed_line_items_all = []
        self.reviewed_line_items_by_tree_id = {}
        self._refresh_reviewed_line_item_filter_options()
        self._clear_tree_rows(self.reviewed_line_items_tree)
        self._clear_tree_rows(self.reviewed_line_items_rollup_tree)
        self._clear_tree_rows(self.sheet_navigator_tree)
        self.summary_banner_text.set("No completed estimate result in this payload yet.")
        self.reviewed_line_items_banner_text.set("No reviewed takeoff line items in this payload yet.")
        self.reviewed_rollup_banner_text.set("No grouped reviewed takeoff totals in this payload yet.")
        self.sheet_banner_text.set("No sheet metadata in this payload yet.")

    def _on_sheet_navigator_select(self, _event: object = None) -> None:
        tree = self.sheet_navigator_tree
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            return
        item_id = selection[0]
        values = tree.item(item_id, "values")
        if not values or len(values) < 2:
            return
        page_text = str(values[0]).strip()
        sheet_id = str(values[1]).strip()
        if not sheet_id or sheet_id == "-":
            return
        self.visual_review_sheet_id.set(sheet_id)
        self.visual_review_page_index.set(page_text if page_text.isdigit() else "")
        result = self.last_result_payload if isinstance(self.last_result_payload, dict) else {}
        if not result:
            return
        filtered = dict(result)
        filtered_sheets: list[dict] = []
        for row in result.get("sheets_detected", []):
            if isinstance(row, dict) and str(row.get("sheet_id", "")).strip() == sheet_id:
                filtered_sheets.append(row)
        if filtered_sheets:
            filtered["sheets_detected"] = filtered_sheets
        self._set_output_json(filtered, sync_views=False, prefer_json_tab=True)

    def _render_json_panel(self) -> None:
        render = self._json_render_result
        if render is None:
            self.json_view_status_text.set("No JSON payload loaded yet.")
            self._write_output_text("")
            return

        mode = self._json_view_mode
        if mode not in {"preview", "full"}:
            mode = "preview"

        if mode == "full" and render.total_chars > _OUTPUT_JSON_FULL_RENDER_MAX_CHARS:
            body = (
                f"[Full JSON view skipped: payload is {render.total_chars:,} chars, "
                f"which exceeds UI safety limit of {_OUTPUT_JSON_FULL_RENDER_MAX_CHARS:,} chars.]\n\n"
                "Use Save Output to export the full JSON payload to disk.\n\n"
                f"{render.text}"
            )
            mode = "preview"
        else:
            body = render.full_text if mode == "full" else render.text
        summary_lines = summarize_payload(self._json_source_payload)
        preface = "\n".join(summary_lines)
        composed = f"{preface}\n\n{body}" if preface else body
        self._write_output_text(composed)

        if mode == "full":
            self.json_view_status_text.set(f"Full JSON: {render.total_chars:,} chars shown.")
        elif render.truncated:
            self.json_view_status_text.set(
                f"Preview JSON: {render.shown_chars:,}/{render.total_chars:,} chars shown."
            )
        else:
            self.json_view_status_text.set(f"Preview JSON: full payload fits ({render.total_chars:,} chars).")

    def _show_json_preview(self) -> None:
        self._json_view_mode = "preview"
        self._render_json_panel()
        if self.results_notebook is not None:
            self.results_notebook.select(3)

    def _show_full_json(self) -> None:
        self._json_view_mode = "full"
        self._render_json_panel()
        if self.results_notebook is not None:
            self.results_notebook.select(3)

    def _write_output_text(self, text: str, *, cap_chars: int | None = None) -> None:
        rendered = text
        if isinstance(cap_chars, int) and cap_chars > 0 and len(rendered) > cap_chars:
            rendered = f"{_OUTPUT_TRIM_NOTICE}\n{rendered[-cap_chars:]}"
        self.output.delete("1.0", END)
        self.output.insert(END, rendered)

    def _trim_output_to_recent_chars(self, *, max_chars: int) -> None:
        if max_chars < 1:
            return
        current = self.output.get("1.0", "end-1c")
        if len(current) <= max_chars:
            return
        trimmed = current[-max_chars:]
        self.output.delete("1.0", END)
        self.output.insert(END, f"{_OUTPUT_TRIM_NOTICE}\n{trimmed}")

    def _set_output_json(
        self,
        payload: dict,
        *,
        sync_views: bool = True,
        prefer_json_tab: bool = False,
    ) -> None:
        self._json_source_payload = payload if isinstance(payload, dict) else {}
        self._json_render_result = render_json_preview(
            self._json_source_payload,
            max_chars=_OUTPUT_JSON_PREVIEW_MAX_CHARS,
        )
        self._json_view_mode = "preview"
        self._render_json_panel()

        if sync_views:
            self._sync_visual_result_views(payload)
            if self.results_notebook is not None:
                result_payload = self._extract_result_payload(payload)
                self.results_notebook.select(0 if result_payload else 3)
        elif prefer_json_tab and self.results_notebook is not None:
            self.results_notebook.select(3)

    def _set_output_text(self, text: str) -> None:
        self._json_source_payload = {}
        self._json_render_result = None
        self.json_view_status_text.set("Text output.")
        self._write_output_text(text, cap_chars=_OUTPUT_LOG_MAX_CHARS)
        self._sync_visual_result_views({})

    def _append_output_line(self, text: str) -> None:
        if not text:
            return
        self.output.insert(END, f"{text}\n")
        self._trim_output_to_recent_chars(max_chars=_OUTPUT_LOG_MAX_CHARS)
        self.output.see(END)

    def _make_job_poll_message(self, job_id: str, status: str) -> str:
        status_text = status or "unknown"
        cycle = self._auto_poll_cycle
        cycle_text = f" (check #{cycle})" if cycle else ""
        if self.auto_poll_interval_ms:
            interval = self.auto_poll_interval_ms // 1000
            return f"Tracking job {job_id}: {status_text}{cycle_text} (checks every {interval}s)"
        return f"Tracking job {job_id}: {status_text}{cycle_text}"

    def _set_run_phase(self, *, phase: str = "", percent: float | None = None) -> None:
        cleaned_phase = phase.strip()
        if cleaned_phase:
            self.run_phase_text.set(f"Phase: {cleaned_phase}")
        elif not (self.request_task_running or self.job_polling or self.file_scan_running):
            self.run_phase_text.set("")
        if percent is not None:
            bounded = max(0.0, min(100.0, float(percent)))
            self.run_progress_value.set(bounded)

    def _phase_from_message(self, message: str) -> tuple[str, float | None]:
        text = message.strip().lower()
        if not text:
            return "", None
        if text.startswith("preparing"):
            return "Preparing files", 8.0
        if text.startswith("attaching"):
            return "Attaching files", 25.0
        if text.startswith("uploading"):
            return "Uploading files", 55.0
        if text.startswith("upload complete"):
            return "Waiting for server analysis", 68.0
        if "tracking job" in text and "queued" in text:
            return "Queued for processing", 76.0
        if "tracking job" in text and "running" in text:
            return "Analyzing drawings", 88.0
        if "tracking job" in text and "completed" in text:
            return "Completed", 100.0
        if "tracking job" in text and ("failed" in text or "canceled" in text):
            return "Stopped", 100.0
        if "running analysis" in text:
            return "Submitting analysis request", 12.0
        return "", None

    def _handle_request_progress_message(self, message: str) -> None:
        self._append_output_line(message)
        phase, percent = self._phase_from_message(message)
        if phase or percent is not None:
            self._set_run_phase(phase=phase, percent=percent)

    def _set_job_polling(self, *, busy: bool, message: str = "") -> None:
        self.job_polling = busy
        if busy:
            candidate = message.strip()
            if candidate:
                self.job_progress_message = candidate
                phase, percent = self._phase_from_message(candidate)
                self._set_run_phase(phase=phase or "Monitoring job", percent=percent)
        else:
            self.job_progress_message = ""
            if not self.request_task_running:
                self._set_run_phase(phase="", percent=0.0)
        self._refresh_progress_indicator()

    def _set_file_scan_busy(self, *, busy: bool, message: str = "") -> None:
        self.file_scan_running = bool(busy)
        if message is not None:
            msg = message.strip()
            if msg:
                self.request_progress_text.set(msg)
                self._set_run_phase(phase=msg, percent=4.0 if busy else 0.0)
            elif not self.file_scan_running:
                self.request_progress_text.set("")
                self._set_run_phase(phase="", percent=0.0)
        self._refresh_progress_indicator()

    def _refresh_progress_indicator(self) -> None:
        should_show_request_progress = self.request_task_running
        should_show_poll_progress = self.job_polling
        should_show_file_scan = self.file_scan_running and not self.request_task_running
        should_show_phase = bool(self.run_phase_text.get().strip()) and (
            should_show_request_progress or should_show_poll_progress or should_show_file_scan
        )

        if should_show_request_progress:
            if not self.request_progress_text.get():
                self.request_progress_text.set("Working...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            if not self._progress_bar_running:
                self.request_progress_bar.start(12)
                self._progress_bar_running = True
            if should_show_phase:
                self.run_phase_label.grid()
                self.run_phase_progress.grid()
            return

        if should_show_poll_progress:
            polling_message = self.job_progress_message.strip()
            self.request_progress_text.set(polling_message or "Monitoring job progress...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            if not self._progress_bar_running:
                self.request_progress_bar.start(12)
                self._progress_bar_running = True
            if should_show_phase:
                self.run_phase_label.grid()
                self.run_phase_progress.grid()
            return

        if should_show_file_scan:
            if not self.request_progress_text.get():
                self.request_progress_text.set("Scanning drawing files...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            if not self._progress_bar_running:
                self.request_progress_bar.start(12)
                self._progress_bar_running = True
            if should_show_phase:
                self.run_phase_label.grid()
                self.run_phase_progress.grid()
            return

        if self._progress_bar_running:
            self.request_progress_bar.stop()
            self._progress_bar_running = False
        self.request_progress_bar.grid_remove()
        self.request_progress_label.grid_remove()
        self.run_phase_label.grid_remove()
        self.run_phase_progress.grid_remove()
        self.request_progress_text.set("")

    def _set_request_busy(self, *, busy: bool, message: str = "") -> None:
        self.request_task_running = busy
        if busy:
            self.request_progress_text.set(message.strip() or "Working...")
            self._set_run_phase(phase=message.strip() or "Working", percent=10.0)
            for control in self._control_widgets.values():
                try:
                    control.configure(state="disabled")
                except Exception:
                    pass
            self._refresh_progress_indicator()
            return

        for control in self._control_widgets.values():
            try:
                control.configure(state="normal")
            except Exception:
                pass
        if not self.job_polling and not self.file_scan_running:
            self._set_run_phase(phase="", percent=0.0)
        self._refresh_progress_indicator()

    def _parse_optional_positive_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float) and value.is_integer():
            parsed = int(value)
            return parsed if parsed > 0 else None
        token = str(value or "").strip()
        if not token.isdigit():
            return None
        parsed = int(token)
        return parsed if parsed > 0 else None

    def _parse_required_positive_float(self, value: object, *, field_name: str) -> float:
        token = str(value or "").strip()
        try:
            parsed = float(token)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number greater than 0.") from exc
        if parsed <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")
        return parsed

    def _format_size_label(self, byte_count: int) -> str:
        if byte_count < 1024:
            return f"{byte_count} B"
        kib = byte_count / 1024.0
        if kib < 1024:
            return f"{kib:.1f} KB"
        mib = kib / 1024.0
        if mib < 1024:
            return f"{mib:.1f} MB"
        gib = mib / 1024.0
        return f"{gib:.2f} GB"

    def _selected_files_summary(self) -> str:
        if not self.files:
            return "No files selected."
        names: list[str] = [Path(path).name for path in self.files]
        total_bytes = 0
        missing = 0
        scanned_pages = 0
        unknown_pages = 0
        for path in self.files:
            try:
                stat = Path(path).stat()
                total_bytes += stat.st_size
                scan = self._file_scan_meta.get(str(Path(path).resolve()))
                page_count = None
                if scan:
                    page_count = scan.get("page_count")
                if page_count is None:
                    unknown_pages += 1
                else:
                    scanned_pages += int(page_count)
            except OSError:
                missing += 1
        shown = ", ".join(names[:3])
        if len(names) > 3:
            shown = f"{shown}, +{len(names) - 3} more"

        size_text = self._format_size_label(total_bytes) if total_bytes > 0 else "size unknown"
        page_text = (
            f", {scanned_pages} pages total"
            if unknown_pages == 0 and self.files and scanned_pages > 0
            else f", {scanned_pages} pages identified"
        )
        if missing > 0:
            page_text = ", pages unknown"
        if missing > 0:
            return (
                f"{len(names)} file(s) selected ({size_text}; {missing} unavailable){page_text}: {shown}"
            )
        return f"{len(names)} file(s) selected ({size_text}{page_text}): {shown}"

    def _refresh_header_summary(self) -> None:
        mode = self.analysis_mode.get().strip() or "auto"
        job_id = self.current_job_id.get().strip()
        self.header_mode_text.set(f"Mode: {mode}")
        self.header_job_text.set(f"Job: {job_id[:12]}..." if job_id else "Job: none")
        if not self.files:
            self.header_files_text.set("Files: none")
        else:
            self.header_files_text.set(f"Files: {len(self.files)} selected")

    def _refresh_trade_selection_hint(self) -> None:
        mode = self.analysis_mode.get().strip() or "auto"
        if mode == "all":
            hint = "All work types will be analyzed."
        elif mode == "auto":
            hint = "Drawings will be scanned to auto-select work types."
        elif mode == "selected":
            hint = "Only selected work types will be analyzed."
        else:
            hint = f"Analysis mode: {mode}"
        self.trade_selection_hint_text.set(hint)

    def _refresh_files_label(self) -> None:
        self.files_label.config(text=self._selected_files_summary())
        self._refresh_files_list()
        self._refresh_header_summary()

    def _refresh_files_list(self) -> None:
        if self.files_list is None:
            return

        self.files_list.configure(state="normal")
        self.files_list.delete("1.0", END)
        if not self.files:
            self.files_list.insert(END, "No files selected.\n")
            self.files_list.configure(state="disabled")
            return

        for idx, path_text in enumerate(self.files, start=1):
            path = Path(path_text)
            name = path.name
            try:
                size = self._format_size_label(path.stat().st_size)
                status = "found"
            except OSError:
                size = "not found"
                status = "missing"
            scan = self._file_scan_meta.get(str(path.resolve()))
            page_segment = ""
            if scan:
                page_count = scan.get("page_count")
                scan_status = str(scan.get("status", "")).lower()
                if scan_status == "error":
                    error = str(scan.get("error", "unreadable"))
                    page_segment = f", pages: n/a ({error})"
                elif page_count is None:
                    page_segment = ", pages: unknown"
                else:
                    page_segment = f", pages: {int(page_count)}"
            else:
                page_segment = ", pages: scanning..."
            self.files_list.insert(END, f"{idx:>2}. {name} ({size}, {status}{page_segment})\n")

        self.files_list.configure(state="disabled")

    def _load_settings(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            raw = self.settings_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
        except Exception as exc:
            self.runtime_logger.warn(f"Settings load failed ({self.settings_path}): {exc}")
            self._settings_io_warning_active = True
            self.status_text.set(
                f"Could not read saved settings. Defaults were loaded. ({self.settings_path.name})"
            )
            return
        if not isinstance(loaded, dict):
            return
        if self._settings_io_warning_active:
            self._settings_io_warning_active = False
            self.status_text.set("Saved settings loaded.")

        api_url = loaded.get("api_url")
        if isinstance(api_url, str) and api_url.strip():
            self.api_url.set(api_url.strip())

        tenant_id = loaded.get("tenant_id")
        if isinstance(tenant_id, str) and tenant_id.strip():
            self.tenant_id.set(tenant_id.strip())

        analysis_mode = loaded.get("analysis_mode")
        if isinstance(analysis_mode, str) and analysis_mode in {"auto", "selected", "all"}:
            self.analysis_mode.set(analysis_mode)
            self.guided_trade_strategy.set(analysis_mode)

        selected_trades = loaded.get("selected_trades")
        if isinstance(selected_trades, str):
            self.selected_trades.set(selected_trades)

        notes = loaded.get("notes")
        if isinstance(notes, str):
            self.notes.set(notes)

        sheet_overrides_path = loaded.get("sheet_overrides_path")
        if isinstance(sheet_overrides_path, str):
            self.sheet_overrides_path.set(sheet_overrides_path)

        spec_profile_ids = loaded.get("spec_profile_ids")
        if isinstance(spec_profile_ids, str):
            self.spec_profile_ids.set(spec_profile_ids)

        spec_organization = loaded.get("spec_organization")
        if isinstance(spec_organization, str):
            self.spec_organization.set(spec_organization)

        include_public_specs = loaded.get("include_public_specs")
        if isinstance(include_public_specs, bool):
            self.include_public_specs.set(include_public_specs)

        publish_uploaded_specs = loaded.get("publish_uploaded_specs")
        if isinstance(publish_uploaded_specs, bool):
            self.publish_uploaded_specs.set(publish_uploaded_specs)

        current_job_id = loaded.get("current_job_id")
        if isinstance(current_job_id, str):
            self.current_job_id.set(current_job_id)

        visual_review_sheet_id = loaded.get("visual_review_sheet_id")
        if isinstance(visual_review_sheet_id, str):
            self.visual_review_sheet_id.set(visual_review_sheet_id.strip())

        visual_review_page_index = loaded.get("visual_review_page_index")
        if isinstance(visual_review_page_index, str):
            self.visual_review_page_index.set(visual_review_page_index.strip())

        scale_measured_pdf_units = loaded.get("scale_measured_pdf_units")
        if isinstance(scale_measured_pdf_units, str):
            self.scale_measured_pdf_units.set(scale_measured_pdf_units.strip())

        scale_known_length_ft = loaded.get("scale_known_length_ft")
        if isinstance(scale_known_length_ft, str):
            self.scale_known_length_ft.set(scale_known_length_ft.strip())

        include_all_template = loaded.get("include_all_template")
        if isinstance(include_all_template, bool):
            self.include_all_template.set(include_all_template)

        include_unmapped_benchmark = loaded.get("include_unmapped_benchmark")
        if isinstance(include_unmapped_benchmark, bool):
            self.include_unmapped_benchmark.set(include_unmapped_benchmark)

        beginner_mode = loaded.get("beginner_mode")
        if isinstance(beginner_mode, bool):
            self.beginner_mode.set(beginner_mode)

        show_advanced_tools = loaded.get("show_advanced_tools")
        if isinstance(show_advanced_tools, bool):
            self.show_advanced_tools.set(show_advanced_tools)

        auto_poll_enabled = loaded.get("auto_poll_enabled")
        if isinstance(auto_poll_enabled, bool):
            self.auto_poll_enabled.set(auto_poll_enabled)

        prune_statuses = loaded.get("prune_statuses")
        if isinstance(prune_statuses, str):
            self.prune_statuses.set(prune_statuses)

        prune_older_than_hours = loaded.get("prune_older_than_hours")
        if isinstance(prune_older_than_hours, str):
            self.prune_older_than_hours.set(prune_older_than_hours)

        prune_limit = loaded.get("prune_limit")
        if isinstance(prune_limit, str):
            self.prune_limit.set(prune_limit)

        prune_cleanup_uploads = loaded.get("prune_cleanup_uploads")
        if isinstance(prune_cleanup_uploads, bool):
            self.prune_cleanup_uploads.set(prune_cleanup_uploads)

        guided_step = loaded.get("guided_step")
        if isinstance(guided_step, str) and guided_step in {"trade", "run"}:
            self.guided_step.set(guided_step)

        guided_trade_strategy = loaded.get("guided_trade_strategy")
        if isinstance(guided_trade_strategy, str) and guided_trade_strategy in {
            "auto",
            "selected",
            "all",
        }:
            self.guided_trade_strategy.set(guided_trade_strategy)

        guided_run_objective = loaded.get("guided_run_objective")
        if isinstance(guided_run_objective, str) and guided_run_objective in {
            "takeoff_and_estimation",
            "takeoff_only",
            "manhours_only",
        }:
            self.guided_run_objective.set(guided_run_objective)

        theme_preset = loaded.get("theme_preset")
        if isinstance(theme_preset, str) and theme_preset in _THEME_PRESETS:
            self.theme_preset.set(
                resolve_theme_preset(theme_preset, migrate_legacy_default=True)
            )

        dark_mode_enabled = loaded.get("dark_mode_enabled")
        if isinstance(dark_mode_enabled, bool):
            self.dark_mode_enabled.set(dark_mode_enabled)

        banner_animation_enabled = loaded.get("banner_animation_enabled")
        if isinstance(banner_animation_enabled, bool):
            self.banner_animation_enabled.set(banner_animation_enabled)

        active_project_name = loaded.get("active_project_name")
        if isinstance(active_project_name, str):
            self.active_project_name.set(active_project_name.strip())

        project_setup_name = loaded.get("project_setup_name")
        if isinstance(project_setup_name, str):
            self.project_setup_name.set(project_setup_name.strip())

        file_list = loaded.get("files")
        if isinstance(file_list, list):
            restored: list[str] = []
            for item in file_list:
                if isinstance(item, str) and item.strip():
                    path = Path(item)
                    if path.exists():
                        restored.append(str(path))
            self.files = restored

        self._apply_beginner_mode(update_status=False)
        self._refresh_guided_flow()
        self._apply_advanced_tools_visibility(update_status=False)
        self._file_scan_meta = {}
        self._file_scan_token += 1
        if self.files:
            self._start_selected_file_scan(self.files)

        if self.auto_poll_enabled.get() and self.current_job_id.get().strip():
            self._start_auto_poll()
        self._refresh_project_selector()

    def _save_settings(self) -> None:
        payload = {
            "api_url": self.api_url.get().strip(),
            "tenant_id": self.tenant_id.get().strip() or "default",
            "analysis_mode": self.analysis_mode.get().strip(),
            "selected_trades": self.selected_trades.get(),
            "notes": self.notes.get(),
            "sheet_overrides_path": self.sheet_overrides_path.get().strip(),
            "spec_profile_ids": self.spec_profile_ids.get().strip(),
            "spec_organization": self.spec_organization.get().strip(),
            "include_public_specs": bool(self.include_public_specs.get()),
            "publish_uploaded_specs": bool(self.publish_uploaded_specs.get()),
            "current_job_id": self.current_job_id.get().strip(),
            "visual_review_sheet_id": self.visual_review_sheet_id.get().strip(),
            "visual_review_page_index": self.visual_review_page_index.get().strip(),
            "scale_measured_pdf_units": self.scale_measured_pdf_units.get().strip(),
            "scale_known_length_ft": self.scale_known_length_ft.get().strip(),
            "include_all_template": bool(self.include_all_template.get()),
            "include_unmapped_benchmark": bool(self.include_unmapped_benchmark.get()),
            "beginner_mode": bool(self.beginner_mode.get()),
            "show_advanced_tools": bool(self.show_advanced_tools.get()),
            "auto_poll_enabled": bool(self.auto_poll_enabled.get()),
            "prune_statuses": self.prune_statuses.get().strip(),
            "prune_older_than_hours": self.prune_older_than_hours.get().strip(),
            "prune_limit": self.prune_limit.get().strip(),
            "prune_cleanup_uploads": bool(self.prune_cleanup_uploads.get()),
            "guided_step": self.guided_step.get().strip(),
            "guided_trade_strategy": self.guided_trade_strategy.get().strip(),
            "guided_run_objective": self.guided_run_objective.get().strip(),
            "theme_preset": self.theme_preset.get().strip(),
            "dark_mode_enabled": bool(self.dark_mode_enabled.get()),
            "banner_animation_enabled": bool(self.banner_animation_enabled.get()),
            "active_project_name": self.active_project_name.get().strip(),
            "project_setup_name": self.project_setup_name.get().strip(),
            "files": self.files,
        }
        try:
            self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self.runtime_logger.warn(f"Settings save failed ({self.settings_path}): {exc}")
            self._settings_io_warning_active = True
            self.status_text.set(
                f"Could not save desktop settings. Check permissions: {self.settings_path.name}"
            )
            return
        if self._settings_io_warning_active:
            self._settings_io_warning_active = False
            self.status_text.set("Settings save restored.")

    def _request_headers(self, *, extra: object = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if isinstance(extra, dict):
            for key, value in extra.items():
                if not isinstance(key, str):
                    continue
                headers[key] = str(value)
        api_key = self.api_key.get().strip()
        if api_key:
            headers["x-api-key"] = api_key
        tenant_id = self.tenant_id.get().strip()
        if tenant_id:
            headers["x-tenant-id"] = tenant_id
        return headers

    def _on_close(self) -> None:
        self._save_settings()
        self._stop_auto_poll()
        if self._banner_after_id is not None:
            try:
                self.root.after_cancel(self._banner_after_id)
            except Exception:
                pass
            self._banner_after_id = None
        for popup in list(self._calculator_popups.values()):
            try:
                popup.destroy()
            except Exception:
                pass
        self._calculator_popups.clear()
        self._close_setup_window()
        self.root.destroy()

    def _shutdown_local_api_clicked(self) -> None:
        if not self._is_local_api_base(self.api_url.get()):
            self.status_text.set("Shutdown API is only available for local host URLs.")
            return
        try:
            stopped = self._shutdown_local_api_process()
            if stopped:
                self.status_text.set("Local API has been stopped.")
            else:
                self.status_text.set("No local API process was tracked by this app.")
        except Exception as exc:
            self._set_output_text(f"Failed to shut down local API:\n{exc}")

    def _check_api_health_clicked(self) -> None:
        try:
            payload = self._request_json("GET", "/health", timeout=10)
            self._set_output_text(format_api_health_payload(payload))
            if isinstance(payload, dict) and payload.get("status") == "ok":
                version = str(payload.get("app_version", "")).strip()
                process_id = str(payload.get("process_id", "")).strip()
                detail = []
                if version:
                    detail.append(f"version {version}")
                if process_id:
                    detail.append(f"pid {process_id}")
                suffix = f" ({', '.join(detail)})" if detail else ""
                self.status_text.set(f"API health ok{suffix}.")
            else:
                self.status_text.set("API health check returned a non-ok status.")
        except Exception as exc:
            self._set_output_text(f"Failed to check API health:\n{exc}")

    def _restart_local_api_clicked(self) -> None:
        if not self._is_local_api_base(self.api_url.get()):
            self.status_text.set("Restart API is only available for local host URLs.")
            return
        self.status_text.set("Restarting local API...")
        worker = Thread(target=self._restart_local_api_worker, daemon=True)
        worker.start()

    def _restart_local_api_worker(self) -> None:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            self.root.after(0, lambda: self.status_text.set("API URL is required."))
            return
        try:
            try:
                self._shutdown_local_api_process()
            except Exception as exc:
                self.root.after(
                    0,
                    lambda: self._append_output_line(f"Local API shutdown warning: {exc}"),
                )
            started = self._ensure_local_api_running(base, force_start=True)
            if started:
                self.root.after(0, lambda: self._append_output_line("Local API restarted."))
                self.root.after(0, lambda: self.status_text.set("Local API restarted."))
            elif self._can_reach_health(base, timeout_seconds=2):
                self.root.after(0, lambda: self._append_output_line("Local API restart skipped: server was still reachable."))
                self.root.after(0, lambda: self.status_text.set("Local API already running."))
            else:
                self.root.after(
                    0,
                    lambda: self.status_text.set("Local API restart did not start a healthy service."),
                )
        except Exception as exc:
            self.root.after(0, lambda: self._set_output_text(f"Local API restart failed:\n{exc}"))


    def _resolve_completed_job_id(self) -> str:
        requested = self.current_job_id.get().strip()
        if requested:
            try:
                detail = self._request_json("GET", f"/v1/jobs/{requested}", timeout=30)
                status = str(detail.get("status", "")).strip()
                if status == "completed":
                    return requested
            except Exception:
                # Fall back to latest completed job.
                pass

        payload = self._request_json("GET", "/v1/jobs?limit=1&status=completed", timeout=30)
        items = payload.get("items", [])
        if not isinstance(items, list) or not items:
            raise RuntimeError("No completed jobs found. Submit and complete a job first.")
        latest = items[0] if isinstance(items[0], dict) else {}
        job_id = str(latest.get("job_id", "")).strip()
        if not job_id:
            raise RuntimeError("Latest completed job is missing job_id.")
        self.current_job_id.set(job_id)
        self._save_settings()
        return job_id

    def _start_local_api_clicked(self) -> None:
        try:
            base = self.api_url.get().strip().rstrip("/")
            if not base:
                raise RuntimeError("API URL is required.")
            self._ensure_local_api_running(base, force_start=True)
            if self._can_reach_health(base, timeout_seconds=2):
                self.status_text.set("Local API is running.")
            else:
                self.status_text.set("Local API start attempted, but health check is not responding yet.")
        except Exception as exc:
            self._set_output_text(f"Failed to start local API:\n{exc}")

    def _start_local_api_if_needed(self) -> None:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            return

        if self._api_bootstrap_in_progress:
            return

        if not self._is_local_api_base(base):
            return

        if self._can_reach_health(base, timeout_seconds=2):
            self.status_text.set("Local API is already running.")
            return

        self._api_bootstrap_in_progress = True
        self._append_output_line(
            "Local API is not running. Starting local API automatically..."
        )
        self.status_text.set("Starting local API automatically...")
        worker = Thread(
            target=self._start_local_api_if_needed_worker,
            args=(base,),
            daemon=True,
        )
        worker.start()

    def _start_local_api_if_needed_worker(self, base: str) -> None:
        try:
            started = self._ensure_local_api_running(base, force_start=True)
            if started:
                self.root.after(
                    0,
                    lambda: self._append_output_line(
                        f"Local API started for {base}."
                    ),
                )
                self.root.after(0, lambda: self.status_text.set("Local API is running."))
            elif self._can_reach_health(base, timeout_seconds=2):
                self.root.after(
                    0,
                    lambda: self._append_output_line("Local API is already reachable."),
                )
                self.root.after(0, lambda: self.status_text.set("Local API is running."))
            else:
                self.root.after(
                    0,
                    lambda: self._append_output_line(
                        "Local API auto-start did not produce a healthy service; use Start Local API."
                    ),
                )
                self.root.after(
                    0,
                    lambda: self.status_text.set(
                        "Local API is not reachable yet. Click 'Start Local API' if needed."
                    ),
                )
        except Exception as exc:
            self.root.after(
                0,
                lambda: self._append_output_line(
                    f"Automatic local API startup failed: {exc}"
                ),
            )
            self.root.after(
                0,
                lambda: self.status_text.set(
                    "Automatic local API startup failed. Click 'Start Local API' to retry."
                ),
            )
        finally:
            self._api_bootstrap_in_progress = False

    def _ensure_local_api_running(self, api_base: str, force_start: bool = False) -> bool:
        if not self._is_local_api_base(api_base):
            return False

        if not force_start and self._can_reach_health(api_base, timeout_seconds=2):
            return False

        if force_start:
            self._shutdown_local_api_process()
        self._spawn_local_api_process()
        return self._wait_for_health(api_base, wait_seconds=8)

    def _is_local_api_base(self, api_base: str) -> bool:
        parsed = urlparse(api_base if "://" in api_base else f"http://{api_base}")
        host = (parsed.hostname or "").lower()
        return host in {"127.0.0.1", "localhost"}

    def _spawn_local_api_process(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        api_exe = project_root / ".venv" / "Scripts" / "ai-estimator-api.exe"
        python_exe = project_root / ".venv" / "Scripts" / "python.exe"

        if api_exe.exists():
            cmd = [str(api_exe)]
        elif python_exe.exists():
            cmd = [str(python_exe), "-m", "service.run_api"]
        else:
            raise RuntimeError(
                "Local API launcher was not found. Reinstall with: python -m pip install -e \".[dev]\""
            )

        popen_kwargs = {
            "cwd": str(project_root),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            popen_kwargs["creationflags"] = create_no_window
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
            startup_info.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
            popen_kwargs["startupinfo"] = startup_info
        else:
            popen_kwargs["start_new_session"] = True

        self._local_api_process = subprocess.Popen(cmd, **popen_kwargs)

    def _shutdown_local_api_process(self) -> bool:
        process = self._local_api_process
        if process is None:
            return False

        if process.poll() is not None:
            self._local_api_process = None
            return False

        process.terminate()
        try:
            process.wait(timeout=4)
        except Exception:
            process.kill()
            process.wait(timeout=2)
        self._local_api_process = None
        return True

    def _wait_for_health(self, api_base: str, wait_seconds: int) -> bool:
        deadline = time.time() + max(1, wait_seconds)
        while time.time() < deadline:
            if self._can_reach_health(api_base, timeout_seconds=2):
                return True
            time.sleep(0.5)
        return False

    def _can_reach_health(self, api_base: str, timeout_seconds: int = 2) -> bool:
        base = api_base.strip().rstrip("/")
        if not base:
            return False
        try:
            response = requests.get(f"{base}/health", timeout=timeout_seconds)
            if response.status_code >= 400:
                return False
            payload = response.json()
            return isinstance(payload, dict) and payload.get("status") == "ok"
        except Exception:
            return False

    def _save_output(self) -> None:
        if self._json_render_result is not None and self._json_source_payload:
            content = self._json_render_result.full_text.strip()
        else:
            content = self.output.get("1.0", END).strip()
        if not content:
            self.status_text.set("Nothing to save.")
            return
        target = filedialog.asksaveasfilename(
            title="Save output JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            self.status_text.set("Save canceled.")
            return
        Path(target).write_text(content, encoding="utf-8")
        self.status_text.set(f"Saved output: {target}")

    def _export_takeoff_csv(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return
        target = filedialog.asksaveasfilename(
            title="Save takeoff CSV",
            initialfile=f"takeoff_{job_id[:8]}.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not target:
            self.status_text.set("Takeoff CSV export canceled.")
            return

        def worker() -> str:
            return self._request_text(
                "GET",
                f"/v1/jobs/{job_id}/takeoff.csv",
                timeout=60,
            )

        def on_success(csv_text: str) -> None:
            Path(target).write_text(csv_text, encoding="utf-8-sig")
            self.status_text.set(f"Takeoff CSV saved: {target}")
            self._set_output_text(f"Takeoff CSV saved:\n{target}")

        self._start_background_action(
            message=f"Exporting takeoff CSV for job {job_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to export takeoff CSV",
            failure_status="Takeoff CSV export failed.",
        )

    def _show_reviewed_takeoff_lines(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return

        def worker() -> dict:
            return self._request_json(
                "GET",
                f"/v1/jobs/{job_id}/takeoff-line-items",
                timeout=60,
            )

        def on_success(payload: dict) -> None:
            self._set_output_text(
                format_reviewed_takeoff_lines_payload(
                    payload,
                    current_job_id=self.current_job_id.get().strip(),
                )
            )
            self._populate_reviewed_line_items_tree(payload.get("line_items", []))
            if self.results_notebook is not None:
                self.results_notebook.select(0)
            item_count = int(payload.get("item_count", 0) or 0)
            self.status_text.set(
                f"Reviewed takeoff lines loaded for job {job_id}: {item_count} item(s)."
            )

        self._start_background_action(
            message=f"Loading reviewed takeoff line items for job {job_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to load reviewed takeoff lines",
            failure_status="Reviewed takeoff line load failed.",
        )

    def _open_estimator_report(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return
        base = self.api_url.get().strip().rstrip("/") or "http://127.0.0.1:8000"
        params: dict[str, str] = {}
        tenant_id = self.tenant_id.get().strip()
        if tenant_id:
            params["tenant_id"] = tenant_id
        query = f"?{urlencode(params)}" if params else ""
        url = f"{base}/v1/jobs/{job_id}/report.html{query}"
        webbrowser.open(url, new=2)
        self.status_text.set(f"Opened estimator report for job {job_id}.")
        self._append_output_line(f"Estimator report opened: {url}")

    def _show_spec_compliance_report(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return

        def worker() -> dict:
            return self._request_json("GET", f"/v1/jobs/{job_id}/spec-compliance", timeout=60)

        def on_success(payload: dict) -> None:
            self._set_output_json(payload)
            status = str(payload.get("status", "unknown")).replace("_", " ")
            self.status_text.set(f"Spec compliance loaded for job {job_id}: {status}.")

        self._start_background_action(
            message=f"Loading spec compliance report for job {job_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to load spec compliance",
            failure_status="Spec compliance failed.",
        )

    def _export_handoff_package(self) -> None:
        try:
            job_id = self._resolve_completed_job_id()
        except Exception as exc:
            self._set_output_text(f"Failed to resolve completed job:\n{exc}")
            return
        target = filedialog.asksaveasfilename(
            title="Save handoff ZIP package",
            initialfile=f"handoff_{job_id[:8]}.zip",
            defaultextension=".zip",
            filetypes=[("ZIP packages", "*.zip"), ("All files", "*.*")],
        )
        if not target:
            self.status_text.set("Handoff package export canceled.")
            return

        def worker() -> bytes:
            return self._request_bytes(
                "GET",
                f"/v1/jobs/{job_id}/handoff.zip",
                timeout=120,
            )

        def on_success(payload: bytes) -> None:
            Path(target).write_bytes(payload)
            self.status_text.set(f"Handoff package saved: {target}")
            self._set_output_text(f"Handoff package saved:\n{target}")

        self._start_background_action(
            message=f"Exporting handoff package for job {job_id}...",
            worker=worker,
            on_success=on_success,
            failure_heading="Failed to export handoff package",
            failure_status="Handoff package export failed.",
        )

    def _show_benchmark_history(self) -> None:
        results_dir = self._results_dir()
        try:
            payload = self._request_json(
                "GET",
                "/v1/benchmark-reports/history",
                timeout=60,
                params={"limit": 50, "offset": 0},
            )
            source = "API"
        except Exception:
            payload = build_benchmark_history(results_dir=results_dir, limit=50, offset=0)
            source = "local fallback"

        self._set_output_json(payload)
        total_reports = payload.get("total_available", 0)
        self.status_text.set(f"Loaded benchmark history ({source}): {total_reports} report(s).")

    def _show_benchmark_trend_snapshot(self) -> None:
        results_dir = self._results_dir()
        try:
            payload = self._request_json(
                "GET",
                "/v1/benchmark-reports/trend",
                timeout=60,
            )
            source = "API"
        except Exception:
            payload = build_latest_benchmark_trend_summary(results_dir)
            source = "local fallback"

        self._set_output_json(payload)
        trend = payload.get("trend", "unknown")
        delta = payload.get("overall_score_delta", "n/a")
        self.status_text.set(f"Loaded latest trend snapshot ({source}): trend={trend}, delta={delta}")

    def _show_benchmark_score_timeline(self) -> None:
        results_dir = self._results_dir()
        try:
            payload = self._request_json(
                "GET",
                "/v1/benchmark-reports/timeline",
                timeout=60,
                params={"limit": 30, "offset": 0},
            )
            source = "API"
        except Exception:
            payload = build_benchmark_score_timeline(results_dir=results_dir, limit=30, offset=0)
            source = "local fallback"

        self._set_output_json(payload)
        total = payload.get("total_available", 0)
        returned = payload.get("total_returned", 0)
        self.status_text.set(f"Loaded score timeline ({source}): {returned}/{total} point(s).")

    def _evaluate_benchmark_quality_gate(self) -> None:
        results_dir = self._results_dir()
        try:
            payload = self._request_json(
                "GET",
                "/v1/benchmark-reports/gate",
                timeout=60,
                params={
                    "require_non_regression": "true",
                    "require_improvement": "false",
                },
            )
            source = "API"
        except Exception:
            payload = evaluate_latest_benchmark_quality_gate(
                results_dir=results_dir,
                require_non_regression=True,
                require_improvement=False,
            )
            source = "local fallback"

        self._set_output_json(payload)
        passed = payload.get("passed")
        status = "PASSED" if passed is True else "FAILED"
        self.status_text.set(f"Benchmark quality gate {status} ({source}).")

    def _show_benchmark_dashboard(self) -> None:
        results_dir = self._results_dir()
        try:
            payload = self._request_json(
                "GET",
                "/v1/benchmark-reports/dashboard",
                timeout=60,
                params={
                    "history_limit": 20,
                    "history_offset": 0,
                    "timeline_limit": 30,
                    "timeline_offset": 0,
                    "gate_require_non_regression": "true",
                    "gate_require_improvement": "false",
                },
            )
            source = "API"
        except Exception:
            payload = build_benchmark_dashboard(
                results_dir=results_dir,
                history_limit=20,
                history_offset=0,
                timeline_limit=30,
                timeline_offset=0,
                gate_require_non_regression=True,
                gate_require_improvement=False,
            )
            source = "local fallback"

        self._set_output_json(payload)
        total = payload.get("total_available", 0)
        warnings = payload.get("warnings", [])
        warning_count = len(warnings) if isinstance(warnings, list) else 0
        self.status_text.set(
            f"Loaded benchmark dashboard ({source}): {total} report(s), {warning_count} warning(s)."
        )

    def _compare_benchmark_reports(self) -> None:
        results_dir = self._results_dir()
        default_dir = results_dir if results_dir.exists() else Path(__file__).resolve().parents[1]

        baseline_path = filedialog.askopenfilename(
            title="Select baseline benchmark report",
            initialdir=str(default_dir),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not baseline_path:
            self.status_text.set("Benchmark report compare canceled.")
            return

        candidate_path = filedialog.askopenfilename(
            title="Select candidate benchmark report",
            initialdir=str(Path(baseline_path).parent),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not candidate_path:
            self.status_text.set("Benchmark report compare canceled.")
            return

        try:
            comparison = self._request_json(
                "GET",
                "/v1/benchmark-reports/compare",
                timeout=120,
                params={"baseline_path": baseline_path, "candidate_path": candidate_path},
            )
            source = "API"
        except Exception:
            comparison = compare_reports_from_paths(
                baseline_path=Path(baseline_path),
                candidate_path=Path(candidate_path),
            )
            source = "local fallback"

        try:
            self._set_output_json(comparison)
            delta = comparison.get("overall_score_delta")
            self.status_text.set(f"Report compare complete ({source}). Overall score delta: {delta}")
        except Exception as exc:
            self._set_output_text(f"Failed to compare benchmark reports:\n{exc}")

    def _compare_latest_benchmark_reports(self) -> None:
        results_dir = self._results_dir()
        try:
            comparison = self._request_json(
                "GET",
                "/v1/benchmark-reports/compare-latest",
                timeout=120,
            )
            source = "API"
        except Exception:
            comparison = compare_latest_benchmark_reports(results_dir)
            source = "local fallback"

        try:
            self._set_output_json(comparison)
            delta = comparison.get("overall_score_delta")
            trend = comparison.get("trend")
            self.status_text.set(
                f"Latest report comparison complete ({source}). Trend: {trend}; delta: {delta}"
            )
        except Exception as exc:
            self._set_output_text(f"Failed to compare latest benchmark reports:\n{exc}")

    def _open_results_folder(self) -> None:
        results_dir = self._results_dir()
        results_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._open_path(results_dir)
            self.status_text.set(f"Opened results folder: {results_dir}")
        except Exception as exc:
            self._set_output_text(f"Failed to open results folder:\n{exc}")

    def _open_path(self, path: Path) -> None:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _results_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "benchmarks" / "results"

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = DesktopEstimatorApp()
    app.run()


if __name__ == "__main__":
    main()
