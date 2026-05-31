from __future__ import annotations

from desktop.output_presenter import render_json_preview, summarize_payload


def test_summarize_payload_for_result_payload() -> None:
    payload = {
        "result": {
            "sheets_detected": [{"sheet_id": "A101"}],
            "legend_and_symbols": {"unknown_symbols": [{"symbol": "X"}]},
            "quantity_takeoff": {
                "counts": {"door": 2, "window": 3},
                "linear": {"explicit_dimensions_total_ft": 12.5},
            },
            "trade_scope": {"analyzed_trades": ["architectural", "electrical"]},
        }
    }

    lines = summarize_payload(payload)

    assert any("Sheets detected: 1" in line for line in lines)
    assert any("Unknown symbols: 1" in line for line in lines)
    assert any("Quantity count total: 5" in line for line in lines)
    assert any("Explicit dimension references: 12.5 ft" in line for line in lines)
    assert any("Trades analyzed: architectural, electrical" in line for line in lines)


def test_render_json_preview_truncates_large_payload() -> None:
    payload = {"k": "x" * 4000}
    rendered = render_json_preview(payload, max_chars=800)

    assert rendered.truncated is True
    assert rendered.shown_chars <= 800
    assert rendered.total_chars > rendered.shown_chars
    assert "JSON preview truncated" in rendered.text


def test_render_json_preview_returns_full_when_small() -> None:
    payload = {"ok": True}
    rendered = render_json_preview(payload, max_chars=800)

    assert rendered.truncated is False
    assert rendered.text == rendered.full_text
    assert rendered.total_chars == rendered.shown_chars
