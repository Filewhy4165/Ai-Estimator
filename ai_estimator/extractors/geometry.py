from __future__ import annotations

import re

from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


DOOR_TAG_RE = re.compile(r"\bD[- ]?(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
WINDOW_TAG_RE = re.compile(r"\bW[- ]?(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
ROOM_RE = re.compile(r"\bROOM\s+([A-Z0-9\-\s]+)", re.IGNORECASE)
DIMENSION_RE = re.compile(r"\b(\d+['’]-\d+[\"]?)\b")


def extract_geometry(
    pages: list[LoadedPage], sheets: list[ClassifiedSheet]
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    sheet_lookup = {sheet.source_page_index: sheet for sheet in sheets}

    walls: list[dict[str, object]] = []
    doors: list[dict[str, object]] = []
    windows: list[dict[str, object]] = []
    slabs: list[dict[str, object]] = []
    roofs: list[dict[str, object]] = []
    fixtures: list[dict[str, object]] = []
    equipment: list[dict[str, object]] = []
    annotations: dict[str, object] = {"rooms": [], "dimensions": [], "callouts": []}

    # Conservative extraction: only extract explicit textual tags and dimensions.
    for page in pages:
        text = page.text or ""
        if not text:
            continue
        sheet = sheet_lookup.get(page.page_index)
        sheet_id = sheet.sheet_id if sheet else f"PAGE_{page.page_index + 1}"
        trade = sheet.trade if sheet else "other"

        for match in DOOR_TAG_RE.findall(text):
            tag = f"D{match}"
            doors.append(
                {
                    "id": f"Door_{sheet_id}_{tag}",
                    "type": "door",
                    "trade": trade,
                    "properties": {"tag": tag},
                    "geometry": {},
                    "relationships": [],
                    "source_sheet": sheet_id,
                }
            )

        for match in WINDOW_TAG_RE.findall(text):
            tag = f"W{match}"
            windows.append(
                {
                    "id": f"Window_{sheet_id}_{tag}",
                    "type": "window",
                    "trade": trade,
                    "properties": {"tag": tag},
                    "geometry": {},
                    "relationships": [],
                    "source_sheet": sheet_id,
                }
            )

        for room in _extract_room_tokens(text):
            annotations["rooms"].append({"sheet_id": sheet_id, "name": room})

        for dim in DIMENSION_RE.findall(text):
            annotations["dimensions"].append({"sheet_id": sheet_id, "value": dim})

    if not (walls or doors or windows or slabs or roofs or fixtures or equipment):
        issues.append(
            "No reliable measurable geometry was extracted from text alone. "
            "Vector path parsing and/or OCR + symbol detection modules are needed for full takeoff."
        )

    return (
        {
            "walls": walls,
            "doors": _dedupe_by_id(doors),
            "windows": _dedupe_by_id(windows),
            "slabs": slabs,
            "roofs": roofs,
            "fixtures": fixtures,
            "equipment": equipment,
            "annotations": annotations,
        },
        issues,
    )


def _dedupe_by_id(items: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for item in items:
        item_id = str(item.get("id", ""))
        if item_id and item_id not in seen:
            seen.add(item_id)
            deduped.append(item)
    return deduped


def _extract_room_tokens(text: str) -> list[str]:
    rooms: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        # Examples:
        # ROOM 102
        # ROOM NAME: MEN
        # MEN ROOM 115
        upper = line.upper()
        if "ROOM" not in upper:
            continue

        match = ROOM_RE.search(line)
        if not match:
            continue
        tail = match.group(1)
        # Stop at long narrative clauses.
        tail = tail.split("  ")[0].split(".")[0].split(";")[0]
        cleaned = " ".join(tail.split())[:60]
        if len(cleaned) < 2:
            continue
        rooms.append(cleaned)
    return _dedupe_strings(rooms, limit=200)


def _dedupe_strings(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out
