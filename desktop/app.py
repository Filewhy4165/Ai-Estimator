from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from tkinter import END, BooleanVar, Label, StringVar, Text, Tk, Toplevel, filedialog, ttk
from urllib.parse import urlparse
import time

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

_TERMINAL_JOB_STATUSES = {"completed", "failed", "canceled"}


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
            background="#111827",
            foreground="#E5E7EB",
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
        self.root.title("AI Estimator Desktop")
        self.root.geometry("1320x820")
        self.root.minsize(1180, 700)
        self.settings_path = Path.home() / ".ai_estimator_desktop_settings.json"

        self.api_url = StringVar(value="http://127.0.0.1:8000")
        self.api_key = StringVar(value=os.environ.get("AI_ESTIMATOR_API_KEY", ""))
        self.analysis_mode = StringVar(value="auto")
        self.selected_trades = StringVar(value="")
        self.sheet_overrides_path = StringVar(value="")
        self.current_job_id = StringVar(value="")
        self.notes = StringVar(value="")
        self.include_all_template = BooleanVar(value=False)
        self.include_unmapped_benchmark = BooleanVar(value=True)
        self.beginner_mode = BooleanVar(value=False)
        self.auto_poll_enabled = BooleanVar(value=False)
        self.prune_statuses = StringVar(value="completed,failed,canceled")
        self.prune_older_than_hours = StringVar(value="168")
        self.prune_limit = StringVar(value="200")
        self.prune_cleanup_uploads = BooleanVar(value=False)
        self.auto_poll_interval_ms = 2000
        self.auto_poll_handle: str | None = None
        self.benchmark_task_running = False
        self.end_to_end_task_running = False
        self.request_task_running = False
        self.request_progress_text = StringVar(value="")
        self.status_text = StringVar(value="Ready.")
        self.trade_catalog: list[str] = []
        self.analysis_mode_catalog: list[str] = ["auto", "selected", "all"]
        self.files: list[str] = []
        self._tooltips: list[HoverTooltip] = []
        self._control_help_entries: dict[str, str] = {}
        self._control_specs: dict[str, dict[str, str]] = {}
        self._control_widgets: dict[str, object] = {}
        self._control_tooltips: dict[str, HoverTooltip] = {}
        self._field_tooltip_specs: dict[str, dict[str, str]] = {}
        self._field_tooltips: dict[str, HoverTooltip] = {}

        self._configure_style()
        self._build_ui()
        self._bind_shortcuts()
        self._load_settings()
        self._refresh_files_label()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available_themes = set(style.theme_names())
        if "clam" in available_themes:
            style.theme_use("clam")
        style.configure("TButton", padding=(8, 4))
        style.configure("TCheckbutton", padding=(4, 2))
        style.configure("Section.TLabel", font=("Segoe UI", 9, "bold"))

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="API URL").grid(row=0, column=0, sticky="w")
        api_row = ttk.Frame(frame)
        api_row.grid(row=0, column=1, sticky="ew")
        api_row.columnconfigure(0, weight=1)
        api_url_entry = ttk.Entry(api_row, textvariable=self.api_url, width=58)
        api_url_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(api_row, text="Start Local API", command=self._start_local_api_clicked).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(api_row, text="Control Guide", command=self._show_control_guide).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(
            api_row,
            text="Beginner Mode",
            variable=self.beginner_mode,
            command=self._toggle_beginner_mode,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(frame, text="API Key (optional)").grid(row=1, column=0, sticky="w")
        api_key_entry = ttk.Entry(frame, textvariable=self.api_key, width=68, show="*")
        api_key_entry.grid(row=1, column=1, sticky="ew")

        ttk.Label(frame, text="Analysis Mode").grid(row=2, column=0, sticky="w")
        self.analysis_mode_combo = ttk.Combobox(
            frame,
            values=self.analysis_mode_catalog,
            textvariable=self.analysis_mode,
            state="readonly",
            width=20,
        )
        self.analysis_mode_combo.grid(row=2, column=1, sticky="w")

        ttk.Label(frame, text="Selected Trades (CSV)").grid(row=3, column=0, sticky="w")
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

        ttk.Label(frame, text="Sheet Overrides JSON").grid(row=4, column=0, sticky="w")
        overrides_row = ttk.Frame(frame)
        overrides_row.grid(row=4, column=1, sticky="ew")
        overrides_row.columnconfigure(0, weight=1)
        overrides_entry = ttk.Entry(overrides_row, textvariable=self.sheet_overrides_path, width=58)
        overrides_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(overrides_row, text="Browse", command=self._choose_overrides_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Label(frame, text="Current Job ID").grid(row=5, column=0, sticky="w")
        current_job_entry = ttk.Entry(frame, textvariable=self.current_job_id, width=68)
        current_job_entry.grid(row=5, column=1, sticky="ew")

        ttk.Label(frame, text="Notes").grid(row=6, column=0, sticky="w")
        notes_entry = ttk.Entry(frame, textvariable=self.notes, width=68)
        notes_entry.grid(row=6, column=1, sticky="ew")

        actions1 = ttk.Frame(frame)
        actions1.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        actions1.columnconfigure(9, weight=1)
        ttk.Button(actions1, text="Choose PDFs", command=self._choose_pdfs).grid(row=0, column=0, sticky="w")
        ttk.Button(actions1, text="Run Analysis", command=self._run_analysis).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions1, text="Submit Async Job", command=self._submit_async_job).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions1, text="Refresh Job", command=self._refresh_job).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions1, text="Load Latest Job", command=self._load_latest_job).grid(
            row=0, column=4, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions1, text="Rerun Job", command=self._rerun_job).grid(
            row=0, column=5, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions1, text="Run End-to-End Benchmark", command=self._run_end_to_end_benchmark).grid(
            row=0, column=6, sticky="w", padx=(8, 0)
        )
        ttk.Button(
            actions1,
            text="Rerun Recommended",
            command=self._rerun_job_with_recommendation,
        ).grid(row=0, column=7, sticky="w", padx=(8, 0))
        ttk.Button(actions1, text="Cancel Job", command=self._cancel_job).grid(
            row=0, column=8, sticky="w", padx=(8, 0)
        )

        actions2 = ttk.Frame(frame)
        actions2.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        actions2.columnconfigure(21, weight=1)
        ttk.Checkbutton(
            actions2,
            text="Template Include All Sheets",
            variable=self.include_all_template,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(actions2, text="Get Review Queue", command=self._get_review_queue).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Export Overrides Template", command=self._export_overrides_template).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Export Benchmark Template", command=self._export_benchmark_template).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(
            actions2,
            text="Benchmark Include Unmapped",
            variable=self.include_unmapped_benchmark,
        ).grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Button(actions2, text="Run Baseline Benchmark", command=self._run_baseline_benchmark).grid(
            row=0, column=5, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Show Benchmark History", command=self._show_benchmark_history).grid(
            row=0, column=6, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Compare Reports", command=self._compare_benchmark_reports).grid(
            row=0, column=7, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Compare Latest Reports", command=self._compare_latest_benchmark_reports).grid(
            row=0, column=8, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Latest Trend Snapshot", command=self._show_benchmark_trend_snapshot).grid(
            row=0, column=9, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Score Timeline", command=self._show_benchmark_score_timeline).grid(
            row=0, column=10, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Evaluate Gate", command=self._evaluate_benchmark_quality_gate).grid(
            row=0, column=11, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Benchmark Dashboard", command=self._show_benchmark_dashboard).grid(
            row=0, column=12, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(
            actions2,
            text="Auto Poll Job",
            variable=self.auto_poll_enabled,
            command=self._toggle_auto_poll,
        ).grid(row=0, column=13, sticky="w", padx=(8, 0))
        ttk.Button(actions2, text="Save Output", command=self._save_output).grid(
            row=0, column=14, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Open Results Folder", command=self._open_results_folder).grid(
            row=0, column=15, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Job Ops Snapshot", command=self._show_job_ops_snapshot).grid(
            row=0, column=16, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Job Ops Gate", command=self._evaluate_job_ops_gate).grid(
            row=0, column=17, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Trade Recommendation", command=self._get_trade_recommendation).grid(
            row=0, column=18, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Trade Coverage", command=self._get_trade_coverage).grid(
            row=0, column=19, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Readiness Report", command=self._get_readiness_report).grid(
            row=0, column=20, sticky="w", padx=(8, 0)
        )

        prune_row = ttk.Frame(frame)
        prune_row.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        prune_row.columnconfigure(10, weight=1)
        ttk.Label(prune_row, text="Prune Statuses").grid(row=0, column=0, sticky="w")
        prune_statuses_entry = ttk.Entry(prune_row, textvariable=self.prune_statuses, width=28)
        prune_statuses_entry.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(prune_row, text="Older Than (h)").grid(row=0, column=2, sticky="w", padx=(12, 0))
        prune_older_than_entry = ttk.Entry(prune_row, textvariable=self.prune_older_than_hours, width=8)
        prune_older_than_entry.grid(
            row=0, column=3, sticky="w", padx=(6, 0)
        )
        ttk.Label(prune_row, text="Limit").grid(row=0, column=4, sticky="w", padx=(12, 0))
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

        self.files_label = ttk.Label(frame, text="No files selected.")
        self.files_label.grid(row=10, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, textvariable=self.status_text).grid(row=11, column=0, columnspan=2, sticky="w", pady=(4, 8))

        progress_row = ttk.Frame(frame)
        progress_row.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        progress_row.columnconfigure(1, weight=1)
        self.request_progress_label = ttk.Label(progress_row, textvariable=self.request_progress_text)
        self.request_progress_label.grid(row=0, column=0, sticky="w")
        self.request_progress_bar = ttk.Progressbar(progress_row, mode="indeterminate", length=260)
        self.request_progress_bar.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.request_progress_label.grid_remove()
        self.request_progress_bar.grid_remove()

        self.output = Text(
            frame,
            wrap="none",
            background="#0B1220",
            foreground="#E5E7EB",
            insertbackground="#E5E7EB",
            padx=8,
            pady=8,
        )
        self.output.grid(row=13, column=0, columnspan=2, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(13, weight=1)
        self._install_tooltips(
            frame=frame,
            api_url_entry=api_url_entry,
            api_key_entry=api_key_entry,
            selected_trades_entry=selected_trades_entry,
            overrides_entry=overrides_entry,
            current_job_entry=current_job_entry,
            notes_entry=notes_entry,
            prune_statuses_entry=prune_statuses_entry,
            prune_older_than_entry=prune_older_than_entry,
            prune_limit_entry=prune_limit_entry,
        )

    def _install_tooltips(
        self,
        *,
        frame: ttk.Frame,
        api_url_entry: ttk.Entry,
        api_key_entry: ttk.Entry,
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
                "pro_tip": "Optional API key header value sent as x-api-key.",
                "beginner_tip": "Optional password for protected API servers.",
            },
            "analysis_mode": {
                "pro_tip": "auto=detect trades, selected=only selected trades, all=analyze all supported trades.",
                "beginner_tip": "Choose how wide the takeoff should run: auto, selected types, or all types.",
            },
            "selected_trades": {
                "pro_tip": "Comma-separated trade tokens. Required when Analysis Mode is set to selected.",
                "beginner_tip": "Type work types separated by commas (example: plumbing,electrical) when using selected mode.",
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
        field_widgets: dict[str, object] = {
            "api_url": api_url_entry,
            "api_key": api_key_entry,
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

        self._apply_beginner_mode(update_status=False)

    def _control_specs_for_ui(self) -> dict[str, dict[str, str]]:
        return {
            "start_local_api": {
                "pro_label": "Start Local API",
                "beginner_label": "Start Local Server",
                "pro_tip": "Start the local backend service at the API URL if it is not already running.",
                "beginner_tip": "Turn on the local engine so this app can run jobs.",
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
            "choose_pdfs": {
                "pro_label": "Choose PDFs",
                "beginner_label": "Pick Drawing Files",
                "pro_tip": "Pick one or more drawing PDFs for analysis or async job submission.",
                "beginner_tip": "Choose the plan drawing files you want to run.",
            },
            "run_analysis": {
                "pro_label": "Run Analysis",
                "beginner_label": "Run Now (Wait)",
                "pro_tip": "Run synchronous analysis and return results directly in this window.",
                "beginner_tip": "Run now and wait here until results finish.",
            },
            "submit_async_job": {
                "pro_label": "Submit Async Job",
                "beginner_label": "Start Background Run",
                "pro_tip": "Submit a background job and return a job ID for polling.",
                "beginner_tip": "Start in background so you can keep working while it runs.",
            },
            "refresh_job": {
                "pro_label": "Refresh Job",
                "beginner_label": "Check Job Status",
                "pro_tip": "Fetch latest status and payload for the current job ID.",
                "beginner_tip": "Check progress for the current background run.",
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

    def _toggle_beginner_mode(self) -> None:
        self._apply_beginner_mode(update_status=True)
        self._save_settings()

    def _apply_beginner_mode(self, *, update_status: bool) -> None:
        use_beginner = bool(self.beginner_mode.get())
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

        self._control_help_entries = {}
        for key, spec in self._control_specs.items():
            label = spec["beginner_label"] if use_beginner else spec["pro_label"]
            description = spec["beginner_tip"] if use_beginner else spec["pro_tip"]
            self._control_help_entries[label] = description

        if update_status:
            mode_text = "Beginner mode enabled." if use_beginner else "Beginner mode disabled."
            self.status_text.set(mode_text)

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
        heading = "AI Estimator Desktop - Beginner Guide" if use_beginner else "AI Estimator Desktop - Control Guide"
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
            "Keyboard shortcuts:",
            "- F1: Show this guide",
            f"- Ctrl+O: {choose_pdfs_label}",
            f"- Ctrl+Enter: {submit_job_label}",
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
        self._refresh_files_label()
        self.status_text.set("PDFs selected." if self.files else "No PDFs selected.")
        self._save_settings()

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

    def _load_trade_catalog(self) -> None:
        try:
            payload = self._refresh_trade_catalog_from_api(update_output=True)
            trade_count = len(self.trade_catalog)
            self.status_text.set(f"Loaded trade catalog: {trade_count} trade(s).")
            self._set_output_json(payload)
        except Exception as exc:
            self._set_output_text(f"Failed to load trade catalog:\n{exc}")

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
            )
            self.root.after(0, lambda: self._on_submit_async_job_success(payload))
        except Exception as exc:
            self.root.after(0, lambda: self._on_submit_async_job_failure(exc))

    def _on_run_analysis_success(self, payload: dict) -> None:
        self._set_request_busy(busy=False)
        self._set_output_json(payload)
        self.status_text.set("Synchronous analysis completed.")

    def _on_run_analysis_failure(self, exc: Exception) -> None:
        self._set_request_busy(busy=False)
        self._set_output_text(f"Failed to run analysis:\n{exc}")
        self.status_text.set("Analysis failed.")

    def _on_submit_async_job_success(self, payload: dict) -> None:
        self._set_request_busy(busy=False)
        job_id = str(payload.get("job_id", "")).strip()
        if not job_id:
            self._set_output_text("Failed to submit async job:\nAPI response did not include job_id.")
            self.status_text.set("Async job submission failed.")
            return
        self.current_job_id.set(job_id)
        self._set_output_json(payload)
        self.status_text.set(f"Async job submitted: {job_id}")
        self._save_settings()
        if self.auto_poll_enabled.get():
            self._start_auto_poll()

    def _on_submit_async_job_failure(self, exc: Exception) -> None:
        self._set_request_busy(busy=False)
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
            self._save_settings()
            if self.auto_poll_enabled.get():
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
            self._save_settings()
            if self.auto_poll_enabled.get():
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
                self.auto_poll_enabled.set(False)
                self._stop_auto_poll()
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
            if status in _TERMINAL_JOB_STATUSES:
                self._stop_auto_poll()
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
            if self.auto_poll_enabled.get():
                latest_status = str(latest.get("status", "")).strip()
                if latest_status not in _TERMINAL_JOB_STATUSES:
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
            )
            job_id = str(create_payload.get("job_id", "")).strip()
            if not job_id:
                raise RuntimeError("API response did not include job_id.")

            job_payload = self._poll_job_until_terminal(
                api_base=api_base,
                job_id=job_id,
                max_wait_seconds=1200,
                poll_interval_seconds=2,
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
        self._set_output_json(payload)
        summary = payload.get("summary", {})
        score = summary.get("overall_score", "n/a") if isinstance(summary, dict) else "n/a"
        self.status_text.set(f"End-to-end benchmark complete. Overall score: {score}")

    def _on_end_to_end_benchmark_failure(self, exc: Exception) -> None:
        self.end_to_end_task_running = False
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
            return
        if self.auto_poll_handle is not None:
            return
        self.status_text.set(f"Auto polling job {job_id} every {self.auto_poll_interval_ms // 1000}s.")
        self.auto_poll_handle = self.root.after(self.auto_poll_interval_ms, self._auto_poll_tick)

    def _stop_auto_poll(self) -> None:
        if self.auto_poll_handle is not None:
            self.root.after_cancel(self.auto_poll_handle)
            self.auto_poll_handle = None

    def _auto_poll_tick(self) -> None:
        self.auto_poll_handle = None
        if not self.auto_poll_enabled.get():
            return
        job_id = self.current_job_id.get().strip()
        if not job_id:
            self.auto_poll_enabled.set(False)
            self.status_text.set("Auto poll stopped: no current job ID.")
            return

        try:
            payload = self._request_json("GET", f"/v1/jobs/{job_id}", timeout=30)
            status = str(payload.get("status", "")).strip()
            result = payload.get("result")
            if status == "completed" and isinstance(result, dict):
                self._set_output_json(result)
                self.status_text.set(f"Job {job_id} completed.")
                self.auto_poll_enabled.set(False)
                self._stop_auto_poll()
                return
            if status in {"failed", "canceled"}:
                self._set_output_json(payload)
                self.status_text.set(f"Job {job_id} {status}.")
                self.auto_poll_enabled.set(False)
                self._stop_auto_poll()
                return
            self._set_output_json(payload)
            self.status_text.set(f"Job {job_id} status: {status or 'unknown'} (auto polling)")
        except Exception as exc:
            self.status_text.set(f"Auto poll error: {exc}")
            self.auto_poll_enabled.set(False)
            self._stop_auto_poll()
            return

        self.auto_poll_handle = self.root.after(self.auto_poll_interval_ms, self._auto_poll_tick)

    def _refresh_trade_catalog_from_api(self, *, update_output: bool) -> dict:
        payload = self._request_json("GET", "/v1/meta/trades", timeout=30)
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

        if update_output:
            self._set_output_json(payload)
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
    ) -> dict:
        files = []
        handles = []
        try:
            for file_path in file_paths:
                handle = open(file_path, "rb")
                handles.append(handle)
                files.append(("files", (Path(file_path).name, handle, "application/pdf")))
            return self._request_json_from_base(
                "POST",
                api_base=api_base,
                path=path,
                data=data,
                files=files,
                timeout=timeout,
            )
        finally:
            for handle in handles:
                handle.close()

    def _poll_job_until_terminal(
        self,
        *,
        api_base: str,
        job_id: str,
        max_wait_seconds: int,
        poll_interval_seconds: int,
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
            time.sleep(max(1, poll_interval_seconds))
        raise RuntimeError(
            f"Timed out waiting for job {job_id}. Last status: {last_payload.get('status', 'unknown')}"
        )

    def _request_json(self, method: str, path: str, *, timeout: int = 60, **kwargs: object) -> dict:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            raise RuntimeError("API URL is required.")
        return self._request_json_from_base(method, api_base=base, path=path, timeout=timeout, **kwargs)

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

    def _set_output_json(self, payload: dict) -> None:
        self.output.delete("1.0", END)
        self.output.insert(END, json.dumps(payload, indent=2))

    def _set_output_text(self, text: str) -> None:
        self.output.delete("1.0", END)
        self.output.insert(END, text)

    def _set_request_busy(self, *, busy: bool, message: str = "") -> None:
        self.request_task_running = busy
        if busy:
            self.request_progress_text.set(message.strip() or "Working...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            self.request_progress_bar.start(12)
            return

        self.request_progress_bar.stop()
        self.request_progress_bar.grid_remove()
        self.request_progress_label.grid_remove()
        self.request_progress_text.set("")

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
        for path in self.files:
            try:
                total_bytes += Path(path).stat().st_size
            except OSError:
                missing += 1
        shown = ", ".join(names[:3])
        if len(names) > 3:
            shown = f"{shown}, +{len(names) - 3} more"

        size_text = self._format_size_label(total_bytes) if total_bytes > 0 else "size unknown"
        if missing > 0:
            return (
                f"{len(names)} file(s) selected ({size_text}; {missing} unavailable): {shown}"
            )
        return f"{len(names)} file(s) selected ({size_text}): {shown}"

    def _refresh_files_label(self) -> None:
        self.files_label.config(text=self._selected_files_summary())

    def _load_settings(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            raw = self.settings_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
        except Exception:
            return
        if not isinstance(loaded, dict):
            return

        api_url = loaded.get("api_url")
        if isinstance(api_url, str) and api_url.strip():
            self.api_url.set(api_url.strip())

        analysis_mode = loaded.get("analysis_mode")
        if isinstance(analysis_mode, str) and analysis_mode in {"auto", "selected", "all"}:
            self.analysis_mode.set(analysis_mode)

        selected_trades = loaded.get("selected_trades")
        if isinstance(selected_trades, str):
            self.selected_trades.set(selected_trades)

        notes = loaded.get("notes")
        if isinstance(notes, str):
            self.notes.set(notes)

        sheet_overrides_path = loaded.get("sheet_overrides_path")
        if isinstance(sheet_overrides_path, str):
            self.sheet_overrides_path.set(sheet_overrides_path)

        current_job_id = loaded.get("current_job_id")
        if isinstance(current_job_id, str):
            self.current_job_id.set(current_job_id)

        include_all_template = loaded.get("include_all_template")
        if isinstance(include_all_template, bool):
            self.include_all_template.set(include_all_template)

        include_unmapped_benchmark = loaded.get("include_unmapped_benchmark")
        if isinstance(include_unmapped_benchmark, bool):
            self.include_unmapped_benchmark.set(include_unmapped_benchmark)

        beginner_mode = loaded.get("beginner_mode")
        if isinstance(beginner_mode, bool):
            self.beginner_mode.set(beginner_mode)

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

        if self.auto_poll_enabled.get() and self.current_job_id.get().strip():
            self._start_auto_poll()

    def _save_settings(self) -> None:
        payload = {
            "api_url": self.api_url.get().strip(),
            "analysis_mode": self.analysis_mode.get().strip(),
            "selected_trades": self.selected_trades.get(),
            "notes": self.notes.get(),
            "sheet_overrides_path": self.sheet_overrides_path.get().strip(),
            "current_job_id": self.current_job_id.get().strip(),
            "include_all_template": bool(self.include_all_template.get()),
            "include_unmapped_benchmark": bool(self.include_unmapped_benchmark.get()),
            "beginner_mode": bool(self.beginner_mode.get()),
            "auto_poll_enabled": bool(self.auto_poll_enabled.get()),
            "prune_statuses": self.prune_statuses.get().strip(),
            "prune_older_than_hours": self.prune_older_than_hours.get().strip(),
            "prune_limit": self.prune_limit.get().strip(),
            "prune_cleanup_uploads": bool(self.prune_cleanup_uploads.get()),
            "files": self.files,
        }
        try:
            self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            # Non-fatal: app should continue even if settings write fails.
            return

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
        return headers

    def _on_close(self) -> None:
        self._save_settings()
        self._stop_auto_poll()
        self.root.destroy()

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

    def _ensure_local_api_running(self, api_base: str, force_start: bool = False) -> bool:
        if not self._is_local_api_base(api_base):
            return False

        if not force_start and self._can_reach_health(api_base, timeout_seconds=2):
            return False

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
            detached = int(getattr(subprocess, "DETACHED_PROCESS", 0))
            popen_kwargs["creationflags"] = create_no_window | detached
        else:
            popen_kwargs["start_new_session"] = True

        subprocess.Popen(cmd, **popen_kwargs)

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
            if os.name == "nt":
                os.startfile(str(results_dir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(results_dir)])
            else:
                subprocess.Popen(["xdg-open", str(results_dir)])
            self.status_text.set(f"Opened results folder: {results_dir}")
        except Exception as exc:
            self._set_output_text(f"Failed to open results folder:\n{exc}")

    def _results_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "benchmarks" / "results"

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = DesktopEstimatorApp()
    app.run()


if __name__ == "__main__":
    main()
