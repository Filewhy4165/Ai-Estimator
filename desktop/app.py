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
from ai_estimator.benchmark_compare import compare_benchmark_reports, compare_latest_benchmark_reports


class DesktopEstimatorApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("AI Estimator Desktop")
        self.root.geometry("1080x760")
        self.settings_path = Path.home() / ".ai_estimator_desktop_settings.json"

        self.api_url = StringVar(value="http://127.0.0.1:8000")
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

        ttk.Label(frame, text="Analysis Mode").grid(row=1, column=0, sticky="w")
        ttk.Combobox(
            frame,
            values=["auto", "selected", "all"],
            textvariable=self.analysis_mode,
            state="readonly",
            width=20,
        ).grid(row=1, column=1, sticky="w")

        ttk.Label(frame, text="Selected Trades (CSV)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.selected_trades, width=68).grid(row=2, column=1, sticky="ew")

        ttk.Label(frame, text="Sheet Overrides JSON").grid(row=3, column=0, sticky="w")
        overrides_row = ttk.Frame(frame)
        overrides_row.grid(row=3, column=1, sticky="ew")
        overrides_row.columnconfigure(0, weight=1)
        ttk.Entry(overrides_row, textvariable=self.sheet_overrides_path, width=58).grid(row=0, column=0, sticky="ew")
        ttk.Button(overrides_row, text="Browse", command=self._choose_overrides_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Label(frame, text="Current Job ID").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.current_job_id, width=68).grid(row=4, column=1, sticky="ew")

        ttk.Label(frame, text="Notes").grid(row=5, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.notes, width=68).grid(row=5, column=1, sticky="ew")

        actions1 = ttk.Frame(frame)
        actions1.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        actions1.columnconfigure(7, weight=1)
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

        actions2 = ttk.Frame(frame)
        actions2.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        actions2.columnconfigure(12, weight=1)
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
        ttk.Checkbutton(
            actions2,
            text="Auto Poll Job",
            variable=self.auto_poll_enabled,
            command=self._toggle_auto_poll,
        ).grid(row=0, column=9, sticky="w", padx=(8, 0))
        ttk.Button(actions2, text="Save Output", command=self._save_output).grid(
            row=0, column=10, sticky="w", padx=(8, 0)
        )
        ttk.Button(actions2, text="Open Results Folder", command=self._open_results_folder).grid(
            row=0, column=11, sticky="w", padx=(8, 0)
        )

        self.files_label = ttk.Label(frame, text="No files selected.")
        self.files_label.grid(row=8, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, textvariable=self.status_text).grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 8))

        self.output = Text(frame, wrap="none")
        self.output.grid(row=10, column=0, columnspan=2, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(10, weight=1)

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
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Overrides JSON is invalid: {exc.msg}") from exc
        if not isinstance(parsed, list):
            raise RuntimeError("Overrides JSON must be a JSON array.")
        data["sheet_overrides_json"] = raw
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
        if not results_dir.exists():
            self._set_output_text(f"No benchmark results directory found:\n{results_dir}")
            return

        items: list[dict[str, object]] = []
        for path in sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            history_item = self._build_benchmark_history_item(path)
            if history_item is not None:
                items.append(history_item)

        payload = {
            "results_dir": str(results_dir),
            "total_reports": len(items),
            "items": items[:50],
        }
        self._set_output_json(payload)
        self.status_text.set(f"Loaded benchmark history: {len(items)} report(s).")

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
            baseline_report = _load_json_dict_file(Path(baseline_path))
            candidate_report = _load_json_dict_file(Path(candidate_path))
            comparison = compare_benchmark_reports(
                baseline_report=baseline_report,
                candidate_report=candidate_report,
                baseline_path=str(baseline_path),
                candidate_path=str(candidate_path),
            )
            self._set_output_json(comparison)
            delta = comparison.get("overall_score_delta")
            self.status_text.set(f"Report compare complete. Overall score delta: {delta}")
        except Exception as exc:
            self._set_output_text(f"Failed to compare benchmark reports:\n{exc}")

    def _compare_latest_benchmark_reports(self) -> None:
        results_dir = self._results_dir()
        try:
            comparison = compare_latest_benchmark_reports(results_dir)
            self._set_output_json(comparison)
            delta = comparison.get("overall_score_delta")
            trend = comparison.get("trend")
            self.status_text.set(f"Latest report comparison complete. Trend: {trend}; delta: {delta}")
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

    def _build_benchmark_history_item(self, path: Path) -> dict[str, object] | None:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None

        summary = parsed.get("summary", {})
        if not isinstance(summary, dict):
            return None
        if "overall_score" not in summary:
            return None

        stat = path.stat()
        modified_local = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        return {
            "file_name": path.name,
            "path": str(path),
            "modified_local": modified_local,
            "generated_at_utc": parsed.get("generated_at_utc"),
            "overall_score": summary.get("overall_score"),
            "case_count": summary.get("case_count"),
            "completed_count": summary.get("completed_count"),
            "failed_count": summary.get("failed_count"),
        }

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = DesktopEstimatorApp()
    app.run()


if __name__ == "__main__":
    main()
