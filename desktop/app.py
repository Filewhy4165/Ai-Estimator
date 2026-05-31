from __future__ import annotations

from datetime import datetime
import math
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable
from threading import Thread
from tkinter import END, BooleanVar, Canvas, Label, Menu, PhotoImage, StringVar, Text, Tk, Toplevel, filedialog, ttk
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
        self.root.title("AI Estimator Command Center")
        self.root.geometry("1440x900")
        self.root.minsize(1200, 740)
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
        self.beginner_mode = BooleanVar(value=True)
        self.show_advanced_tools = BooleanVar(value=False)
        self.auto_poll_enabled = BooleanVar(value=False)
        self.prune_statuses = StringVar(value="completed,failed,canceled")
        self.prune_older_than_hours = StringVar(value="168")
        self.prune_limit = StringVar(value="200")
        self.prune_cleanup_uploads = BooleanVar(value=False)
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
        self.theme_preset = StringVar(value="construction_orange")
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
        self.job_progress_message = ""
        self._progress_bar_running = False
        self._auto_poll_cycle = 0
        self.status_text = StringVar(value="Ready.")
        self.header_mode_text = StringVar(value="Mode: auto")
        self.header_job_text = StringVar(value="Job: none")
        self.header_files_text = StringVar(value="Files: none")
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
        self._calculator_popups: dict[str, Toplevel] = {}
        self.logo_image: PhotoImage | None = None
        self.logo_label: Label | None = None
        self.logo_path_candidates: list[Path] = [
            Path(__file__).resolve().parents[1] / "desktop" / "assets" / "tech_build_logo.png",
            Path(r"C:\Users\sthom\OneDrive\----!!!!TechBuild!!!!----\Tech Build Solutions Logos\1.png"),
        ]
        self.output_y_scroll: ttk.Scrollbar | None = None
        self.output_x_scroll: ttk.Scrollbar | None = None

        self.analysis_mode.trace_add("write", lambda *_: self._refresh_header_summary())
        self.analysis_mode.trace_add("write", lambda *_: self._sync_analysis_mode_to_guided())
        self.current_job_id.trace_add("write", lambda *_: self._refresh_header_summary())
        self.guided_step.trace_add("write", lambda *_: self._refresh_guided_flow())
        self.guided_trade_strategy.trace_add("write", lambda *_: self._sync_guided_trade_strategy())
        self.theme_preset.trace_add("write", lambda *_: self._apply_visual_theme(update_status=True))
        self.dark_mode_enabled.trace_add("write", lambda *_: self._apply_visual_theme(update_status=True))
        self.banner_animation_enabled.trace_add("write", lambda *_: self._toggle_banner_animation())

        self._configure_style()
        self._build_ui()
        self._bind_shortcuts()
        self._load_settings()
        self._refresh_files_label()
        self.root.after(700, self._start_local_api_if_needed)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _resolve_theme_palette(self) -> dict[str, str]:
        preset = self.theme_preset.get().strip() or "construction_orange"
        if preset not in _THEME_PRESETS:
            preset = "construction_orange"
        surfaces = _DARK_SURFACES if bool(self.dark_mode_enabled.get()) else _LIGHT_SURFACES
        palette = {
            **_THEME,
            **surfaces,
            **_THEME_PRESETS[preset],
        }
        palette["danger"] = "#FF3B4F"
        return palette

    def _apply_visual_theme(self, *, update_status: bool) -> None:
        palette = self._resolve_theme_palette()
        _THEME.update(palette)
        self._configure_style()

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
        logo_path: Path | None = None
        for candidate in self.logo_path_candidates:
            if candidate.exists():
                logo_path = candidate
                break
        try:
            self.logo_label.configure(background=_THEME["surface"])
        except Exception:
            pass

        if logo_path is None:
            self.logo_image = None
            try:
                self.logo_label.configure(image="", text="")
            except Exception:
                pass
            return

        try:
            image = PhotoImage(file=str(logo_path))
            max_width = 140
            max_height = 50
            down_x = max(1, math.ceil(image.width() / max_width))
            down_y = max(1, math.ceil(image.height() / max_height))
            downsample = max(down_x, down_y)
            if downsample > 1:
                image = image.subsample(downsample, downsample)
            self.logo_image = image
            self.logo_label.configure(image=self.logo_image, text="")
        except Exception:
            self.logo_image = None
            self.logo_label.configure(image="", text="Tech Build Solutions", fg=_THEME["muted"])

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

        self.root.configure(menu=menu)

    def _build_ui(self) -> None:
        p = _THEME
        container = ttk.Frame(self.root, padding=(18, 16, 18, 16), style="App.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        self._build_menu()

        header = ttk.Frame(container, style="Hero.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="AI Estimator Command Center", style="HeaderTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="AI-powered takeoff, scope intelligence, benchmark gates, and handoff-ready estimating",
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

        frame = ttk.Frame(container, padding=14, style="Panel.TFrame")
        frame.grid(row=3, column=0, sticky="nsew")
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
            values=[
                "construction_orange",
                "electric_blue",
                "lime_steel",
            ],
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
        api_key_entry = ttk.Entry(frame, textvariable=self.api_key, width=68, show="*")
        api_key_entry.grid(row=1, column=1, sticky="ew")

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

        self.guided_flow_frame = ttk.LabelFrame(
            workflow_tab,
            text="Guided Start (Step-by-Step)",
            padding=8,
        )
        self.guided_flow_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
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
        workflow_run.grid(row=1, column=0, sticky="ew")
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
        workflow_benchmark.grid(row=2, column=0, sticky="ew", pady=(8, 0))
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
        ttk.Label(
            calculators_tab,
            text="Trade Calculators: field math for piping, concrete, sheet metal/HVAC, earthwork, and framing.",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        pipe_frame = ttk.LabelFrame(
            calculators_tab,
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
            calculators_tab,
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
            calculators_tab,
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
            calculators_tab,
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
            calculators_tab,
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
        self.request_progress_label = ttk.Label(progress_row, textvariable=self.request_progress_text)
        self.request_progress_label.grid(row=0, column=0, sticky="w")
        self.request_progress_bar = ttk.Progressbar(progress_row, mode="indeterminate", length=260)
        self.request_progress_bar.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.request_progress_label.grid_remove()
        self.request_progress_bar.grid_remove()

        output_frame = ttk.Frame(frame)
        output_frame.grid(row=12, column=0, columnspan=2, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self.output = Text(
            output_frame,
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
        self.output.grid(row=0, column=0, sticky="nsew")
        self.output_y_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        self.output_y_scroll.grid(row=0, column=1, sticky="ns")
        self.output_x_scroll = ttk.Scrollbar(output_frame, orient="horizontal", command=self.output.xview)
        self.output_x_scroll.grid(row=1, column=0, sticky="ew")
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
        self._refresh_guided_flow()
        self._apply_advanced_tools_visibility(update_status=False)
        self._install_company_logo()
        self._apply_visual_theme(update_status=False)

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
                "pro_tip": (
                    "Optional API key sent as x-api-key. Required only when remote service enforces auth."
                ),
                "beginner_tip": (
                    "Optional security key. Leave empty for local server; use one for protected remote servers."
                ),
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
            "choose_pdfs": {
                "pro_label": "Choose PDFs",
                "beginner_label": "Pick Drawing Files",
                "pro_tip": "Pick one or more drawing PDFs for analysis or async job submission.",
                "beginner_tip": "Choose the plan drawing files you want to run.",
            },
            "quick_start": {
                "pro_label": "Quick Start",
                "beginner_label": "Start Estimate",
                "pro_tip": "Recommended one-click flow: ensure files are selected, submit async job, and auto-poll status.",
                "beginner_tip": "Main button to start estimating in the background and watch progress automatically.",
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
                "title": "Pipe Trades Full Calculator",
                "result_var": self.pipe_calc_result,
                "compute": self._recalc_pipe_takeoff,
                "notes": "Use this for feet/inches run math, count multipliers, and field waste.",
                "fields": [
                    ("Length (ft)", self.pipe_length_feet),
                    ("Length (in)", self.pipe_length_inches),
                    ("Run Count", self.pipe_run_count),
                    ("Waste %", self.pipe_waste_percent),
                ],
            },
            "concrete": {
                "title": "Concrete / Gravel Full Calculator",
                "result_var": self.concrete_calc_result,
                "compute": self._recalc_concrete_takeoff,
                "notes": "Use this for slab/pad volume with waste and rough tonnage planning.",
                "fields": [
                    ("Length (ft)", self.concrete_length_feet),
                    ("Width (ft)", self.concrete_width_feet),
                    ("Depth (in)", self.concrete_depth_inches),
                    ("Waste %", self.concrete_waste_percent),
                ],
            },
            "hvac": {
                "title": "Sheet Metal / HVAC Full Calculator",
                "result_var": self.hvac_calc_result,
                "compute": self._recalc_hvac_takeoff,
                "notes": "Use this for round duct sheet area, circumference wrap, and linear footage.",
                "fields": [
                    ("Duct Diameter (in)", self.hvac_diameter_inches),
                    ("Run Length (ft)", self.hvac_run_length_feet),
                    ("Run Count", self.hvac_run_count),
                    ("Waste %", self.hvac_waste_percent),
                ],
            },
            "heavy": {
                "title": "Heavy Earthwork Full Calculator",
                "result_var": self.heavy_calc_result,
                "compute": self._recalc_heavy_takeoff,
                "notes": "Use this for bank vs loose cubic yards and haul tonnage planning.",
                "fields": [
                    ("Area (sq ft)", self.heavy_area_sqft),
                    ("Depth (in)", self.heavy_depth_inches),
                    ("Swell %", self.heavy_swell_percent),
                ],
            },
            "carpentry": {
                "title": "Carpentry Framing Full Calculator",
                "result_var": self.carpentry_calc_result,
                "compute": self._recalc_carpentry_takeoff,
                "notes": "Use this for framing studs, plate length, and board-feet material.",
                "fields": [
                    ("Wall Length (ft)", self.carpentry_wall_length_feet),
                    ("Wall Height (ft)", self.carpentry_wall_height_feet),
                    ("Stud Spacing (in)", self.carpentry_stud_spacing_inches),
                    ("Waste %", self.carpentry_waste_percent),
                ],
            },
        }
        config = configs.get(calculator_key)
        if config is None:
            return

        popup = Toplevel(self.root)
        popup.title(str(config["title"]))
        popup.geometry("760x440")
        popup.minsize(700, 380)
        popup.configure(background=_THEME["app_bg"])
        self._calculator_popups[calculator_key] = popup

        shell = ttk.Frame(popup, padding=14, style="Panel.TFrame")
        shell.pack(fill="both", expand=True, padx=14, pady=14)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        ttk.Label(shell, text=str(config["title"]), style="HeaderTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            shell,
            text=str(config["notes"]),
            style="HeaderSub.TLabel",
            wraplength=680,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        form = ttk.LabelFrame(shell, text="Inputs", padding=10)
        form.grid(row=2, column=0, sticky="nsew")
        for col in range(4):
            form.columnconfigure(col, weight=1)

        fields = config["fields"]
        if isinstance(fields, list):
            for idx, item in enumerate(fields):
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                label_text, value_var = item
                row = idx // 2
                col_base = (idx % 2) * 2
                ttk.Label(form, text=str(label_text)).grid(row=row, column=col_base, sticky="w", pady=(0, 4))
                ttk.Entry(form, textvariable=value_var, width=18).grid(
                    row=row, column=col_base + 1, sticky="w", padx=(6, 16), pady=(0, 4)
                )

        action_row = ttk.Frame(shell)
        action_row.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        action_row.columnconfigure(2, weight=1)
        compute = config["compute"]
        if callable(compute):
            ttk.Button(
                action_row,
                text="Calculate",
                style="Primary.TButton",
                command=compute,
            ).grid(row=0, column=0, sticky="w")
        close_button = ttk.Button(action_row, text="Close")
        close_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        result_var = config["result_var"]
        ttk.Label(
            action_row,
            textvariable=result_var,
            style="Section.TLabel",
        ).grid(row=0, column=2, sticky="e")

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

    def _load_trade_catalog(self) -> None:
        try:
            payload = self._refresh_trade_catalog_from_api(update_output=True)
            trade_count = len(self.trade_catalog)
            self._populate_trade_options(self.trade_catalog, preserve_selected=True, select_all=False)
            self.status_text.set(f"Loaded trade catalog: {trade_count} trade(s).")
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
                progress_callback=lambda message: self.root.after(0, lambda: self._append_output_line(message)),
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
                progress_callback=lambda message: self.root.after(0, lambda: self._append_output_line(message)),
            )
            self.root.after(0, lambda: self._on_submit_async_job_success(payload))
        except Exception as exc:
            self.root.after(0, lambda: self._on_submit_async_job_failure(exc))

    def _on_run_analysis_success(self, payload: dict) -> None:
        self._set_request_busy(busy=False)
        self._set_job_polling(busy=False)
        self._set_output_json(payload)
        self.status_text.set("Synchronous analysis completed.")

    def _on_run_analysis_failure(self, exc: Exception) -> None:
        self._set_request_busy(busy=False)
        self._set_job_polling(busy=False)
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
        self._append_output_line(f"Async job accepted: {job_id}")
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
            self._set_job_polling(
                busy=False if status in _TERMINAL_JOB_STATUSES else self.job_polling,
                message=self._make_job_poll_message(job_id, status),
            )
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
                progress_callback=lambda message: self.root.after(0, lambda: self._append_output_line(message)),
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
                    0, lambda: self._append_output_line(message)
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
                self._set_job_polling(busy=False)
                self.auto_poll_enabled.set(False)
                self._stop_auto_poll()
                return
            if status in {"failed", "canceled"}:
                self._set_output_json(payload)
                self.status_text.set(f"Job {job_id} {status}.")
                self._set_job_polling(busy=False)
                self.auto_poll_enabled.set(False)
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

    def _append_output_line(self, text: str) -> None:
        if not text:
            return
        self.output.insert(END, f"{text}\n")
        self.output.see(END)

    def _make_job_poll_message(self, job_id: str, status: str) -> str:
        status_text = status or "unknown"
        cycle = self._auto_poll_cycle
        cycle_text = f" (check #{cycle})" if cycle else ""
        if self.auto_poll_interval_ms:
            interval = self.auto_poll_interval_ms // 1000
            return f"Tracking job {job_id}: {status_text}{cycle_text} (checks every {interval}s)"
        return f"Tracking job {job_id}: {status_text}{cycle_text}"

    def _set_job_polling(self, *, busy: bool, message: str = "") -> None:
        self.job_polling = busy
        if busy:
            candidate = message.strip()
            if candidate:
                self.job_progress_message = candidate
        else:
            self.job_progress_message = ""
        self._refresh_progress_indicator()

    def _set_file_scan_busy(self, *, busy: bool, message: str = "") -> None:
        self.file_scan_running = bool(busy)
        if message is not None:
            msg = message.strip()
            if msg:
                self.request_progress_text.set(msg)
            elif not self.file_scan_running:
                self.request_progress_text.set("")
        self._refresh_progress_indicator()

    def _refresh_progress_indicator(self) -> None:
        should_show_request_progress = self.request_task_running
        should_show_poll_progress = self.job_polling
        should_show_file_scan = self.file_scan_running and not self.request_task_running

        if should_show_request_progress:
            if not self.request_progress_text.get():
                self.request_progress_text.set("Working...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            if not self._progress_bar_running:
                self.request_progress_bar.start(12)
                self._progress_bar_running = True
            return

        if should_show_poll_progress:
            polling_message = self.job_progress_message.strip()
            self.request_progress_text.set(polling_message or "Monitoring job progress...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            if not self._progress_bar_running:
                self.request_progress_bar.start(12)
                self._progress_bar_running = True
            return

        if should_show_file_scan:
            if not self.request_progress_text.get():
                self.request_progress_text.set("Scanning drawing files...")
            self.request_progress_label.grid()
            self.request_progress_bar.grid()
            if not self._progress_bar_running:
                self.request_progress_bar.start(12)
                self._progress_bar_running = True
            return

        if self._progress_bar_running:
            self.request_progress_bar.stop()
            self._progress_bar_running = False
        self.request_progress_bar.grid_remove()
        self.request_progress_label.grid_remove()
        self.request_progress_text.set("")

    def _set_request_busy(self, *, busy: bool, message: str = "") -> None:
        self.request_task_running = busy
        if busy:
            self.request_progress_text.set(message.strip() or "Working...")
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
        self._refresh_progress_indicator()

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
            self.theme_preset.set(theme_preset)

        dark_mode_enabled = loaded.get("dark_mode_enabled")
        if isinstance(dark_mode_enabled, bool):
            self.dark_mode_enabled.set(dark_mode_enabled)

        banner_animation_enabled = loaded.get("banner_animation_enabled")
        if isinstance(banner_animation_enabled, bool):
            self.banner_animation_enabled.set(banner_animation_enabled)

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
            detached = int(getattr(subprocess, "DETACHED_PROCESS", 0))
            popen_kwargs["creationflags"] = create_no_window | detached
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
