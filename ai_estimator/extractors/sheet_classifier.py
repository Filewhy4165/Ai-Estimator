from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_estimator.constants import DISCIPLINE_PREFIX_TO_TRADE, SHEET_TYPE_MAP, TRADE_KEYWORDS
from ai_estimator.extractors.pdf_loader import LoadedPage


SHEET_ID_RE = re.compile(r"\b([A-Z]{1,2})[-\s]?(\d{2,4}[A-Z]?)\b")


@dataclass
class ClassifiedSheet:
    sheet_id: str
    title: str
    sheet_type: str
    trade: str
    confidence: float
    source_page_index: int
    source_pdf: str


def _extract_sheet_id(text: str) -> str:
    match = SHEET_ID_RE.search(text.upper())
    if not match:
        return ""
    return f"{match.group(1)}{match.group(2)}"


def _score_trade_from_keywords(text: str) -> tuple[str, float]:
    normalized = text.lower()
    scores: dict[str, int] = {}
    for trade, words in TRADE_KEYWORDS.items():
        score = 0
        for word in words:
            if word in normalized:
                score += 1
        if score > 0:
            scores[trade] = score

    if not scores:
        return "other", 0.0

    top_trade = max(scores, key=scores.get)
    max_score = scores[top_trade]
    confidence = min(0.35 + (0.12 * max_score), 0.95)
    return top_trade, confidence


def classify_sheets(
    pages: list[LoadedPage],
    sheet_overrides: list[dict[str, str]] | None = None,
) -> list[ClassifiedSheet]:
    overrides_by_index: dict[int, dict[str, str]] = {}
    for index, override in enumerate(sheet_overrides or []):
        overrides_by_index[index] = override

    sheets: list[ClassifiedSheet] = []
    for page in pages:
        override = overrides_by_index.get(page.page_index, {})
        candidate_text = (override.get("title", "") + "\n" + page.text).strip()

        sheet_id = override.get("sheet_id", "") or _extract_sheet_id(candidate_text)
        title = override.get("title", "") or _best_effort_title(candidate_text)

        trade_from_prefix = "other"
        prefix_conf = 0.0
        sheet_type = "other"
        if sheet_id:
            discipline, sequence = _split_sheet_id(sheet_id)
            trade_from_prefix = DISCIPLINE_PREFIX_TO_TRADE.get(discipline, "other")
            prefix_conf = 0.88 if trade_from_prefix != "other" else 0.2
            if sequence:
                type_digit = sequence[0]
                sheet_type = SHEET_TYPE_MAP.get(type_digit, "other")

        trade_from_keywords, keyword_conf = _score_trade_from_keywords(candidate_text)
        if prefix_conf >= keyword_conf:
            final_trade = trade_from_prefix
            confidence = prefix_conf
        else:
            final_trade = trade_from_keywords
            confidence = keyword_conf

        if not sheet_id:
            sheet_id = f"UNMAPPED_{Path(page.source_pdf).name}_{page.page_index + 1}"
            confidence = min(confidence, 0.45)

        sheets.append(
            ClassifiedSheet(
                sheet_id=sheet_id,
                title=title,
                sheet_type=sheet_type,
                trade=final_trade,
                confidence=round(confidence, 3),
                source_page_index=page.page_index,
                source_pdf=page.source_pdf,
            )
        )
    return sheets


def _split_sheet_id(sheet_id: str) -> tuple[str, str]:
    match = SHEET_ID_RE.match(sheet_id)
    if not match:
        if len(sheet_id) >= 2 and sheet_id[0].isalpha() and sheet_id[1].isalpha():
            return sheet_id[:2], sheet_id[2:]
        if len(sheet_id) >= 1:
            return sheet_id[:1], sheet_id[1:]
        return "", ""
    return match.group(1), match.group(2)


def _best_effort_title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Untitled Sheet"
    for line in lines[:15]:
        if len(line) > 6 and any(ch.isalpha() for ch in line):
            return line[:120]
    return lines[0][:120]
