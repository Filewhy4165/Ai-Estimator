from __future__ import annotations

import re

from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


LEGEND_TRIGGER_RE = re.compile(r"\blegend\b|\bsymbol\b", re.IGNORECASE)
PAIR_RE = re.compile(r"^\s*([A-Za-z0-9\-/()#]{1,24})\s{2,}(.+?)\s*$")
SYMBOL_TOKEN_RE = re.compile(r"\b[A-Z]{1,4}[-_][0-9]{1,3}[A-Z]?\b")


def extract_legend_and_symbols(
    pages: list[LoadedPage], sheets: list[ClassifiedSheet]
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    sheet_lookup = {sheet.source_page_index: sheet for sheet in sheets}
    legends: list[dict[str, object]] = []
    unknown_symbols: list[dict[str, object]] = []
    unknown_seen: set[tuple[str, str]] = set()

    for page in pages:
        text = page.text or ""
        if not text:
            continue
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue

        # Only inspect windows around explicit legend/symbol headings.
        trigger_indexes = [
            index for index, line in enumerate(lines) if LEGEND_TRIGGER_RE.search(line)
        ]
        if not trigger_indexes:
            continue

        sheet = sheet_lookup.get(page.page_index)
        sheet_id = sheet.sheet_id if sheet else f"PAGE_{page.page_index + 1}"
        entries: list[dict[str, str]] = []

        for trigger_index in trigger_indexes:
            window = lines[trigger_index : trigger_index + 60]
            for raw_line in window:
                line = raw_line.strip()
                pair = PAIR_RE.match(line)
                if pair and _is_reasonable_definition(pair.group(2)):
                    entries.append(
                        {
                            "symbol": pair.group(1).upper(),
                            "definition": " ".join(pair.group(2).split())[:160],
                        }
                    )

                for token in SYMBOL_TOKEN_RE.findall(line.upper()):
                    key = (sheet_id, token)
                    if key in unknown_seen:
                        continue
                    if any(item["symbol"] == token for item in entries):
                        continue
                    unknown_seen.add(key)
                    unknown_symbols.append(
                        {
                            "sheet_id": sheet_id,
                            "symbol": token,
                            "classification": f"unclassified_symbol_{len(unknown_symbols) + 1}",
                        }
                    )

        dedup_entries = _dedupe_entries(entries)
        if dedup_entries:
            legends.append({"sheet_id": sheet_id, "entries": dedup_entries})

    if not legends:
        issues.append("No legend or symbol tables were confidently extracted from page text.")

    return {"legends_by_sheet": legends, "unknown_symbols": unknown_symbols[:500]}, issues


def _dedupe_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in entries:
        key = (item["symbol"], item["definition"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _is_reasonable_definition(definition: str) -> bool:
    normalized = " ".join((definition or "").split())
    if len(normalized) < 2 or len(normalized) > 180:
        return False
    if not any(ch.isalpha() for ch in normalized):
        return False
    return True

