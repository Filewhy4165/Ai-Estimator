from pathlib import Path

from service.app import (
    _resolve_rerun_inputs,
    _resolve_uploaded_pdf_paths,
    _should_cleanup_uploads,
)


def test_should_cleanup_defaults_sync_true_async_false(monkeypatch):
    monkeypatch.delenv("AI_ESTIMATOR_CLEANUP_UPLOADS", raising=False)
    monkeypatch.delenv("AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS", raising=False)
    monkeypatch.delenv("AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS", raising=False)
    assert _should_cleanup_uploads(mode="sync") is True
    assert _should_cleanup_uploads(mode="async") is False


def test_should_cleanup_respects_global_and_specific(monkeypatch):
    monkeypatch.setenv("AI_ESTIMATOR_CLEANUP_UPLOADS", "true")
    monkeypatch.delenv("AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS", raising=False)
    monkeypatch.delenv("AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS", raising=False)
    assert _should_cleanup_uploads(mode="sync") is True
    assert _should_cleanup_uploads(mode="async") is True

    monkeypatch.setenv("AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS", "false")
    assert _should_cleanup_uploads(mode="async") is False


def test_resolve_uploaded_pdf_paths_detects_missing(tmp_path: Path):
    exists_path = tmp_path / "a.pdf"
    exists_path.write_bytes(b"pdf")
    missing_path = tmp_path / "missing.pdf"

    source_input = {
        "uploaded_files": [
            {"path": str(exists_path)},
            {"path": str(missing_path)},
            {"path": str(exists_path)},
        ]
    }
    paths, missing = _resolve_uploaded_pdf_paths(source_input)
    assert paths == [str(exists_path)]
    assert missing == [str(missing_path)]


def test_resolve_rerun_inputs_uses_source_defaults():
    source_input = {
        "analysis_mode": "selected",
        "selected_trades": ["architectural", "invalid_trade"],
        "sheet_overrides": [{"sheet_id": "A101", "title": "Floor Plan", "source_page_index": "2"}],
        "notes": "  hello world  ",
    }
    mode, trades, overrides, notes = _resolve_rerun_inputs(
        source_input=source_input,
        analysis_mode=None,
        selected_trades=None,
        sheet_overrides_json=None,
        notes=None,
    )
    assert mode == "selected"
    assert trades == ["architectural"]
    assert overrides == [{"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 2}]
    assert notes == "hello world"


def test_resolve_rerun_inputs_rejects_invalid_mode():
    try:
        _resolve_rerun_inputs(
            source_input={},
            analysis_mode="bad-mode",
            selected_trades=None,
            sheet_overrides_json=None,
            notes=None,
        )
    except ValueError as exc:
        assert "analysis_mode" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid analysis_mode")
