from __future__ import annotations

import json
from pathlib import Path
from tkinter import END, StringVar, Text, Tk, filedialog, ttk

import requests


class DesktopEstimatorApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("AI Estimator Desktop")
        self.root.geometry("980x700")

        self.api_url = StringVar(value="http://127.0.0.1:8000")
        self.analysis_mode = StringVar(value="auto")
        self.selected_trades = StringVar(value="")
        self.files: list[str] = []

        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="API URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.api_url, width=60).grid(row=0, column=1, sticky="ew")

        ttk.Label(frame, text="Analysis Mode").grid(row=1, column=0, sticky="w")
        ttk.Combobox(
            frame,
            values=["auto", "selected", "all"],
            textvariable=self.analysis_mode,
            state="readonly",
            width=20,
        ).grid(row=1, column=1, sticky="w")

        ttk.Label(frame, text="Selected Trades (CSV)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.selected_trades, width=60).grid(row=2, column=1, sticky="ew")

        ttk.Button(frame, text="Choose PDFs", command=self._choose_pdfs).grid(row=3, column=0, sticky="w")
        ttk.Button(frame, text="Run Analysis", command=self._run_analysis).grid(row=3, column=1, sticky="w")
        ttk.Button(frame, text="Save Output", command=self._save_output).grid(row=3, column=1, sticky="e")

        self.files_label = ttk.Label(frame, text="No files selected.")
        self.files_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 8))

        self.output = Text(frame, wrap="none")
        self.output.grid(row=5, column=0, columnspan=2, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

    def _choose_pdfs(self) -> None:
        selected = filedialog.askopenfilenames(
            title="Select drawing PDFs",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        self.files = list(selected)
        if self.files:
            self.files_label.config(text=f"{len(self.files)} file(s) selected.")
        else:
            self.files_label.config(text="No files selected.")

    def _run_analysis(self) -> None:
        self.output.delete("1.0", END)
        if not self.files:
            self.output.insert(END, "Please select at least one PDF.")
            return

        url = self.api_url.get().rstrip("/") + "/v1/analyze"
        data = {
            "analysis_mode": self.analysis_mode.get(),
            "selected_trades": self.selected_trades.get(),
        }
        files = []
        handles = []
        try:
            for file_path in self.files:
                handle = open(file_path, "rb")
                handles.append(handle)
                files.append(("files", (Path(file_path).name, handle, "application/pdf")))

            response = requests.post(url, data=data, files=files, timeout=600)
            if response.status_code >= 400:
                self.output.insert(END, f"Request failed ({response.status_code}):\n{response.text}")
                return
            payload = response.json()
            self.output.insert(END, json.dumps(payload, indent=2))
        except Exception as exc:
            self.output.insert(END, f"Failed to run analysis:\n{exc}")
        finally:
            for handle in handles:
                handle.close()

    def _save_output(self) -> None:
        content = self.output.get("1.0", END).strip()
        if not content:
            return
        target = filedialog.asksaveasfilename(
            title="Save output JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return
        Path(target).write_text(content, encoding="utf-8")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = DesktopEstimatorApp()
    app.run()


if __name__ == "__main__":
    main()

