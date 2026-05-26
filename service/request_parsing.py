from __future__ import annotations

from typing import Any

from ai_estimator.sheet_overrides import parse_sheet_overrides_json as _parse_sheet_overrides_json


def parse_sheet_overrides_json(raw: str | None) -> list[dict[str, Any]] | None:
    return _parse_sheet_overrides_json(raw)


def normalize_notes(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return text[:2000]
