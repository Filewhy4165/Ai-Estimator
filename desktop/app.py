from __future__ import annotations

import json
from pathlib import Path
from tkinter import END, BooleanVar, StringVar, Text, Tk, filedialog, ttk

import requests


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
        self.auto_poll_enabled = BooleanVar(value=False)
        self.auto_poll_interval_ms = 2000
        self.auto_poll_handle: str | None = None
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
        ttk.Entry(frame, textvariable=self.api_url, width=68).grid(row=0, column=1, sticky="ew")

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
        actions1.columnconfigure(5, weight=1)
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

        actions2 = ttk.Frame(frame)
        actions2.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        actions2.columnconfigure(6, weight=1)
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
        ttk.Checkbutton(
            actions2,
            text="Auto Poll Job",
            variable=self.auto_poll_enabled,
            command=self._toggle_auto_poll,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Button(actions2, text="Save Output", command=self._save_output).grid(
            row=0, column=4, sticky="w", padx=(8, 0)
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

    def _request_json(self, method: str, path: str, *, timeout: int = 60, **kwargs: object) -> dict:
        base = self.api_url.get().strip().rstrip("/")
        if not base:
            raise RuntimeError("API URL is required.")
        url = f"{base}{path}"
        response = requests.request(method, url, timeout=timeout, **kwargs)
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

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = DesktopEstimatorApp()
    app.run()


if __name__ == "__main__":
    main()
