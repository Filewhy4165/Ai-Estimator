from __future__ import annotations

import re

from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


DOOR_TAG_RE = re.compile(r"\bD[- ]?(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
WINDOW_TAG_RE = re.compile(r"\bW[- ]?(\d{1,3}[A-Z]?)\b", re.IGNORECASE)
SYMBOL_TAG_RE = re.compile(r"\b([A-Z]{1,6})[-_](\d{1,4}[A-Z]?)\b", re.IGNORECASE)
ROOM_RE = re.compile(r"\bROOM\s+([A-Z0-9\-\s]+)", re.IGNORECASE)
ROOM_NAME_NUMBER_RE = re.compile(r"\b([A-Z][A-Z0-9/&\-]{1,20})\s+ROOM\s+(\d{1,4}[A-Z]?)\b", re.IGNORECASE)
DIMENSION_RE = re.compile(r"(?<!\d)(\d+\s*'\s*-\s*\d+\s*\"?)")


FIXTURE_PREFIX_TO_KIND: dict[str, str] = {
    "WC": "water_closet",
    "UR": "urinal",
    "LAV": "lavatory",
    "LV": "lavatory",
    "SNK": "sink",
    "KS": "kitchen_sink",
    "MS": "mop_sink",
    "FD": "floor_drain",
    "FS": "floor_sink",
    "DF": "drinking_fountain",
    "EWC": "drinking_fountain",
    "HB": "hose_bibb",
    "BT": "bathtub",
    "SH": "shower",
    "FCO": "cleanout",
}


EQUIPMENT_PREFIX_TO_KIND: dict[str, str] = {
    "AHU": "air_handling_unit",
    "RTU": "roof_top_unit",
    "FCU": "fan_coil_unit",
    "EF": "exhaust_fan",
    "SF": "supply_fan",
    "CHLR": "chiller",
    "CH": "chiller",
    "PUMP": "pump",
    "WH": "water_heater",
    "GI": "grease_interceptor",
    "TP": "trap_primer",
    "SAT": "speaker",
    "DSW": "device_switch",
    "PN": "panel",
}


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
    seen_room_pairs: set[tuple[str, str]] = set()
    seen_dimension_pairs: set[tuple[str, str]] = set()

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

        fixture_tags, equipment_tags = _extract_symbol_tags(text)
        for tag, kind in fixture_tags:
            fixtures.append(
                {
                    "id": f"Fixture_{sheet_id}_{tag}",
                    "type": "fixture",
                    "trade": trade,
                    "properties": {"tag": tag, "kind": kind},
                    "geometry": {},
                    "relationships": [],
                    "source_sheet": sheet_id,
                }
            )

        for tag, kind in equipment_tags:
            equipment.append(
                {
                    "id": f"Equipment_{sheet_id}_{tag}",
                    "type": "equipment",
                    "trade": trade,
                    "properties": {"tag": tag, "kind": kind},
                    "geometry": {},
                    "relationships": [],
                    "source_sheet": sheet_id,
                }
            )

        for room in _extract_room_tokens(text):
            key = (sheet_id, room.upper())
            if key in seen_room_pairs:
                continue
            seen_room_pairs.add(key)
            annotations["rooms"].append({"sheet_id": sheet_id, "name": room})

        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            # Avoid extracting scale notations as geometry dimensions.
            if "SCALE" in line.upper():
                continue
            for dim in DIMENSION_RE.findall(line):
                normalized_dim = _normalize_dimension_token(dim)
                if not normalized_dim:
                    continue
                key = (sheet_id, normalized_dim)
                if key in seen_dimension_pairs:
                    continue
                seen_dimension_pairs.add(key)
                annotations["dimensions"].append({"sheet_id": sheet_id, "value": normalized_dim})

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
            "fixtures": _dedupe_by_id(fixtures),
            "equipment": _dedupe_by_id(equipment),
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
    blocked_tokens = {
        "NAME",
        "FLOOR",
        "BASE",
        "WALL",
        "WALLS",
        "CEILING",
        "GENERAL",
        "LEGEND",
        "NOTES",
        "IDENTIFICATION",
    }
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
        # Handle "MEN ROOM 115" style labels first.
        name_num = ROOM_NAME_NUMBER_RE.search(line)
        if name_num:
            room_name = name_num.group(1).strip().upper()
            room_number = name_num.group(2).strip().upper()
            rooms.append(f"{room_name} {room_number}")
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
        tokens = cleaned.upper().split()
        if len(tokens) > 4:
            continue
        if not any(ch.isdigit() for ch in cleaned):
            continue
        if any(token in blocked_tokens for token in tokens):
            continue
        rooms.append(cleaned)
    return _dedupe_strings(rooms, limit=200)


def _extract_symbol_tags(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    fixtures: list[tuple[str, str]] = []
    equipment: list[tuple[str, str]] = []
    seen_fixture_tags: set[str] = set()
    seen_equipment_tags: set[str] = set()

    for prefix_raw, suffix_raw in SYMBOL_TAG_RE.findall((text or "").upper()):
        prefix = prefix_raw.strip().upper()
        suffix = suffix_raw.strip().upper()
        if not prefix or not suffix:
            continue
        tag = f"{prefix}-{suffix}"

        fixture_kind = FIXTURE_PREFIX_TO_KIND.get(prefix)
        if fixture_kind:
            if tag not in seen_fixture_tags:
                seen_fixture_tags.add(tag)
                fixtures.append((tag, fixture_kind))
            continue

        equipment_kind = EQUIPMENT_PREFIX_TO_KIND.get(prefix)
        if equipment_kind:
            if tag not in seen_equipment_tags:
                seen_equipment_tags.add(tag)
                equipment.append((tag, equipment_kind))
            continue

    return fixtures, equipment


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


def _normalize_dimension_token(raw: str) -> str | None:
    token = "".join((raw or "").split())
    if not token:
        return None
    if "'" not in token or "-" not in token:
        return None
    return token
