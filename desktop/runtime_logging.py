from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DesktopLogPaths:
    directory: Path
    file_path: Path


class DesktopRuntimeLogger:
    def __init__(self, app_name: str = "EstimateForge") -> None:
        base = Path.home() / "AppData" / "Local"
        safe_name = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in app_name).strip("_")
        if not safe_name:
            safe_name = "EstimateForge"
        log_dir = base / safe_name / "logs"
        self._paths = DesktopLogPaths(directory=log_dir, file_path=log_dir / "desktop.log")
        self._lock = Lock()

    @property
    def paths(self) -> DesktopLogPaths:
        return self._paths

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def _write(self, level: str, message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        line = f"{_utc_now_iso()} [{level}] {text}\n"
        with self._lock:
            self._paths.directory.mkdir(parents=True, exist_ok=True)
            with self._paths.file_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

