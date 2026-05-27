from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from tkinter import END, BooleanVar, StringVar, Text, Tk, filedialog, ttk
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


class DesktopEstimatorApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("AI Estimator Desktop")
        self.root.geometry("1080x760")
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
        self.auto_poll_enabled = BooleanVar(value=False)
        self.auto_poll_interval_ms = 2000
        self.auto_poll_handle: str | None = None
        self.benchmark_task_running = False
        self.end_to_end_task_running = False
        self.status_text = StringVar(value="Ready.")
        self.files: list[str] = []

        self._build_ui()
        self._load_settings()
        self._refresh_files_label()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="API URL").grid(row=0, column=0, sticky="w")
        api_row = ttk.Frame(frame)
        api_row.grid(row=0, column=1, sticky="ew")
        api_row.columnconfigure(0, weight=1)
        ttk.Entry(api_row, textvariable=self.api_url, width=58).grid(row=0, column=0, sticky="ew")
        ttk.Button(api_row, text="Start Local API", command=self._start_local_api_clicked).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Label(frame, text="API Key (optional)").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.api_key, width=68, show="*").grid(row=1, column=1, sticky="ew")

        ttk.Label(frame, text="Analysis Mode").grid(row=2, column=0, sticky="w")
        ttk.Combobox(
            frame,
            values=["auto", "selected", "all"],
            textvariable=self.analysis_mode,
            state="readonly",
            width=20,
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(frame, text="Selected Trades (CSV)").grid(row=3, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.selected_trades, width=68).grid(row=3, column=1, sticky="ew")

        ttk.Label(frame, text="Sheet Overrides JSON").grid(row=4, column=0, sticky="w")
        overrides_row = ttk.Frame(frame)
        overrides_row.grid(row=4, column=1, sticky="ew")
        overrides_row.columnconfigure(0, weight=1)
        ttk.Entry(overrides_row, textvariable=self.sheet_overrides_path, width=58).grid(row=0, column=0, sticky="ew")
        ttk.Button(overrides_row, text="Browse", command=self._choose_overrides_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Label(frame, text="Current Job ID").grid(row=5, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.current_job_id, width=68).grid(row=5, column=1, sticky="ew")

        ttk.Label(frame, text="Notes").grid(row=6, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.notes, width=68).grid(row=6, column=1, sticky="ew")

        actions1 = ttk.Frame(frame)
        actions1.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        actions1.columnconfigure(8, weight=1)
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

        self.files_label = ttk.Label(frame, text="No files selected.")
        self.files_label.grid(row=9, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, textvariable=self.status_text).grid(row=10, column=0, columnspan=2, sticky="w", pady=(4, 8))

        self.output = Text(frame, wrap="none")
        self.output.grid(row=11, column=0, columnspan=2, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(11, weight=1)

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

    def _run_analysis(self) -> None:
        self.output.delete("1.0", END)
        if not self.files:
            self.output.insert(END, "Please select at least one PDF.")
            return

        try:
            data = self._build_request_data()
            payload = self._post_files("/v1/analyze", data=data, timeout=600)
            self._set_output_json(payload)
            self.status_text.set("Synchronous analysis completed.")
        except Exception as exc:
            self._set_output_text(f"Failed to run analysis:\n{exc}")

    def _submit_async_job(self) -> None:
        self.output.delete("1.0", END)
        if not self.files:
            self.output.insert(END, "Please select at least one PDF.")
            return

        try:
            data = self._build_request_data()
            payload = self._post_files("/v1/jobs", data=data, timeout=120)
            job_id = str(payload.get("job_id", "")).strip()
            if not job_id:
                raise RuntimeError("API response did not include job_id.")
            self.current_job_id.set(job_id)
            self._set_output_json(payload)
            self.status_text.set(f"Async job submitted: {job_id}")
            self._save_settings()
            if self.auto_poll_enabled.get():
                self._start_auto_poll()
        except Exception as exc:
            self._set_output_text(f"Failed to submit async job:\n{exc}")

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
            if status in {"completed", "failed"}:
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
                if latest_status not in {"completed", "failed"}:
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
            failure_rate = payload.get("failure_rate", "n/a")
            self.status_text.set(
                "Loaded job ops snapshot: "
                f"queued={queued}, running={running}, failed={failed}, failure_rate={failure_rate}"
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
            if status == "failed":
                self._set_output_json(payload)
                self.status_text.set(f"Job {job_id} failed.")
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

    def _build_request_data(self) -> dict[str, str]:
        data = {
            "analysis_mode": self.analysis_mode.get(),
            "selected_trades": self.selected_trades.get(),
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
            if status in {"completed", "failed"}:
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

    def _refresh_files_label(self) -> None:
        if self.files:
            self.files_label.config(text=f"{len(self.files)} file(s) selected.")
        else:
            self.files_label.config(text="No files selected.")

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

        auto_poll_enabled = loaded.get("auto_poll_enabled")
        if isinstance(auto_poll_enabled, bool):
            self.auto_poll_enabled.set(auto_poll_enabled)

        file_list = loaded.get("files")
        if isinstance(file_list, list):
            restored: list[str] = []
            for item in file_list:
                if isinstance(item, str) and item.strip():
                    path = Path(item)
                    if path.exists():
                        restored.append(str(path))
            self.files = restored

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
            "auto_poll_enabled": bool(self.auto_poll_enabled.get()),
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
