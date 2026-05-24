from __future__ import annotations

import re

from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


LEGEND_TRIGGER_RE = re.compile(r"\blegend\b|\bsymbol\b", re.IGNORECASE)
PAIR_RE = re.compile(r"^\s*([A-Za-z0-9\-/()#]+)\s{2,}(.+?)\s*$")
SYMBOL_TOKEN_RE = re.compile(r"\b[A-Z]{1,4}[-_][0-9]{1,3}\b")


def extract_legend_and_symbols(
    pages: list[LoadedPage], sheets: list[ClassifiedSheet]
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    sheet_lookup = {sheet.source_page_index: sheet for sheet in sheets}
    legends: list[dict[str, object]] = []
    unknown_symbols: list[dict[str, object]] = []

    for page in pages:
        text = page.text or ""
        if not text:
            continue
        if not LEGEND_TRIGGER_RE.search(text):
            continue

        sheet = sheet_lookup.get(page.page_index)
        sheet_id = sheet.sheet_id if sheet else f"PAGE_{page.page_index + 1}"
        entries = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            pair = PAIR_RE.match(line)
            if pair and len(pair.group(2)) >= 2:
                entries.append({"symbol": pair.group(1), "definition": pair.group(2)})

            for token in SYMBOL_TOKEN_RE.findall(line):
                if not any(item["symbol"] == token for item in entries):
                    unknown_symbols.append(
                        {
                            "sheet_id": sheet_id,
                            "symbol": token,
                            "classification": f"unclassified_symbol_{len(unknown_symbols) + 1}",
                        }
                    )

        legends.append({"sheet_id": sheet_id, "entries": entries})

    if not legends:
        issues.append("No legend or symbol tables were confidently extracted from page text.")

    return {"legends_by_sheet": legends, "unknown_symbols": unknown_symbols}, issues

