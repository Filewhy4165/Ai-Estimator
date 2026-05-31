from __future__ import annotations

from pathlib import Path

import desktop.runtime_logging as runtime_logging


def test_runtime_logger_writes_log_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime_logging.Path, "home", lambda: tmp_path)

    logger = runtime_logging.DesktopRuntimeLogger("EstimateForge")
    logger.info("hello world")

    assert logger.paths.file_path.exists()
    content = logger.paths.file_path.read_text(encoding="utf-8")
    assert "[INFO] hello world" in content


def test_runtime_logger_sanitizes_app_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime_logging.Path, "home", lambda: tmp_path)

    logger = runtime_logging.DesktopRuntimeLogger("Estimate Forge!?")
    logger.warn("sanitized")

    assert "Estimate_Forge" in str(logger.paths.directory)
