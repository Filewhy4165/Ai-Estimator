from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class JsonRenderResult:
    text: str
    full_text: str
    truncated: bool
    total_chars: int
    shown_chars: int


def summarize_payload(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    result = payload.get("result")
    if isinstance(result, dict):
        sheets = result.get("sheets_detected")
        unknown_symbols = result.get("legend_and_symbols", {}).get("unknown_symbols")
        quantity_takeoff = result.get("quantity_takeoff", {})
        quantity = quantity_takeoff.get("counts") if isinstance(quantity_takeoff, dict) else {}
        linear = quantity_takeoff.get("linear") if isinstance(quantity_takeoff, dict) else {}
        annotations = result.get("geometry", {}).get("annotations", {})
        vector_pages = annotations.get("vector_pages") if isinstance(annotations, dict) else []
        trades = result.get("trade_scope", {}).get("analyzed_trades")

        lines.append("Result snapshot:")
        lines.append(f"- Sheets detected: {len(sheets) if isinstance(sheets, list) else 0}")
        lines.append(
            f"- Unknown symbols: {len(unknown_symbols) if isinstance(unknown_symbols, list) else 0}"
        )
        if isinstance(quantity, dict) and quantity:
            total_count = 0
            for value in quantity.values():
                if isinstance(value, (int, float)):
                    total_count += int(value)
            lines.append(f"- Quantity count total: {total_count}")
        if isinstance(linear, dict) and linear.get("explicit_dimensions_total_ft") is not None:
            lines.append(
                f"- Explicit dimension references: {linear.get('explicit_dimensions_total_ft')} ft"
            )
        if isinstance(vector_pages, list) and vector_pages:
            lines.append(f"- Vector evidence pages: {len(vector_pages)}")
        if isinstance(linear, dict) and linear.get("vector_linework_total_ft") is not None:
            lines.append(f"- Scaled vector linework: {linear.get('vector_linework_total_ft')} ft")
        if isinstance(trades, list) and trades:
            lines.append(f"- Trades analyzed: {', '.join(str(x) for x in trades)}")
    elif "items" in payload and isinstance(payload.get("items"), list):
        lines.append(f"List payload snapshot: {len(payload.get('items', []))} item(s)")
    else:
        lines.append("Payload snapshot: no result section detected.")
    return lines


def render_json_preview(payload: dict[str, Any], *, max_chars: int = 240000) -> JsonRenderResult:
    full_text = json.dumps(payload, indent=2)
    total_chars = len(full_text)
    if total_chars <= max_chars:
        return JsonRenderResult(
            text=full_text,
            full_text=full_text,
            truncated=False,
            total_chars=total_chars,
            shown_chars=total_chars,
        )

    head = full_text[: max_chars]
    preview_note = (
        "\n\n---\n"
        f"JSON preview truncated at {max_chars:,} chars (total {total_chars:,}). "
        "Use 'Show Full JSON' to view full payload.\n"
    )
    shown = len(head)
    return JsonRenderResult(
        text=head + preview_note,
        full_text=full_text,
        truncated=True,
        total_chars=total_chars,
        shown_chars=shown,
    )

