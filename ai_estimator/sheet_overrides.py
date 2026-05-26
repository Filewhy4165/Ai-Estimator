from __future__ import annotations

import json
import re
from typing import Any


OVERRIDE_SHEET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]{0,79}$")


def parse_sheet_overrides_json(raw: str | None) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid sheet_overrides_json: {exc.msg}") from exc

    return normalize_sheet_overrides_items(loaded, source_name="sheet_overrides_json")


def normalize_sheet_overrides_items(
    loaded: Any, *, source_name: str = "sheet_overrides_json"
) -> list[dict[str, Any]]:
    if not isinstance(loaded, list):
        raise ValueError(f"{source_name} must be a JSON array.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(loaded):
        if not isinstance(item, dict):
            raise ValueError(f"{source_name}[{index}] must be an object.")
        sheet_id = str(item.get("sheet_id", "")).strip()
        title = str(item.get("title", "")).strip()
        if sheet_id and not _is_reasonable_override_sheet_id(sheet_id):
            if not title:
                # Common user mistake: title entered in sheet_id field.
                title = sheet_id
                sheet_id = ""
            else:
                raise ValueError(
                    f"{source_name}[{index}].sheet_id is invalid. "
                    "Use letters/numbers/hyphen/underscore/dot (no spaces)."
                )

        source_page_index = _parse_optional_page_index(item.get("source_page_index"))
        if source_page_index is None and "source_page_index" in item:
            raise ValueError(f"{source_name}[{index}].source_page_index must be a positive integer.")

        row: dict[str, Any] = {"sheet_id": sheet_id, "title": title}
        if source_page_index is not None:
            row["source_page_index"] = source_page_index
        normalized.append(row)
    return normalized


def _parse_optional_page_index(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            return None
        return value if value >= 1 else None
    return None


def _is_reasonable_override_sheet_id(value: str) -> bool:
    token = value.strip()
    if not token:
        return False
    if not OVERRIDE_SHEET_ID_RE.match(token):
        return False
    if not any(ch.isdigit() for ch in token):
        return False
    if not any(ch.isalpha() for ch in token):
        return False
    return True
