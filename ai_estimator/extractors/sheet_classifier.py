from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_estimator.constants import DISCIPLINE_PREFIX_TO_TRADE, SHEET_TYPE_MAP, TRADE_KEYWORDS
from ai_estimator.extractors.pdf_loader import LoadedPage


SHEET_ID_RE = re.compile(r"\b([A-Z]{1,2})[-\s]?(\d{1,4}(?:\.\d{1,2})?[A-Z]?)\b")
COMPLEX_SHEET_ID_RE = re.compile(r"\b([A-Z0-9]{2,}(?:-[A-Z0-9]{1,12}){2,})\b")
SHEET_ID_LINE_HINTS_RE = re.compile(
    r"\b(sheet|drawing|title|plan|elevation|section|detail|schedule)\b", re.IGNORECASE
)
STRONG_TITLE_HINTS_RE = re.compile(
    r"\b(plan|elevation|section|detail|schedule|legend|diagram)\b", re.IGNORECASE
)
SCALE_METADATA_RE = re.compile(r"\bSCALE\b\s*[:=]", re.IGNORECASE)
ALLOWED_PREFIXES = set(DISCIPLINE_PREFIX_TO_TRADE.keys())


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
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    # Title blocks are commonly near top/bottom, so prioritize those zones.
    candidate_lines = lines[:40] + lines[-40:]
    best_sheet_id = ""
    best_score = -1
    for line in candidate_lines:
        for candidate in _extract_complex_sheet_id_candidates(line):
            score = _complex_sheet_id_score(candidate, line)
            if score > best_score:
                best_score = score
                best_sheet_id = candidate
        for match in SHEET_ID_RE.finditer(line.upper()):
            prefix = match.group(1)
            sequence = match.group(2)
            if prefix not in ALLOWED_PREFIXES:
                continue
            if not _is_valid_sheet_sequence(sequence):
                continue
            score = _sheet_id_score(prefix, sequence, line)
            if score > best_score:
                best_score = score
                best_sheet_id = f"{prefix}{sequence}"

    if best_sheet_id:
        return best_sheet_id

    # Conservative fallback across the full extracted page text.
    for line in lines:
        for candidate in _extract_complex_sheet_id_candidates(line):
            return candidate

    for match in SHEET_ID_RE.finditer(text.upper()):
        prefix = match.group(1)
        sequence = match.group(2)
        if prefix not in ALLOWED_PREFIXES:
            continue
        if _is_valid_sheet_sequence(sequence):
            return f"{prefix}{sequence}"
    return ""


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
    sheet_overrides: list[dict[str, object]] | None = None,
) -> list[ClassifiedSheet]:
    overrides_by_index = _build_overrides_by_index(pages, sheet_overrides or [])

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
            if sequence and sequence[0].isdigit():
                sheet_type = SHEET_TYPE_MAP.get(sequence[0], "other")

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
    parsed_complex = _parse_complex_sheet_id(sheet_id.upper())
    if parsed_complex is not None:
        prefix, sequence, _ = parsed_complex
        return prefix, sequence

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

    for line in lines[:60]:
        if len(line) <= 6 or not any(ch.isalpha() for ch in line):
            continue
        if _looks_like_grid_label(line):
            continue
        if _is_metadata_label(line):
            continue
        if _is_boilerplate_notice(line):
            continue
        if STRONG_TITLE_HINTS_RE.search(line):
            return line[:120]
        if SHEET_ID_LINE_HINTS_RE.search(line):
            return line[:120]

    for line in lines[:60]:
        if (
            len(line) > 6
            and any(ch.isalpha() for ch in line)
            and not _looks_like_grid_label(line)
            and not _is_metadata_label(line)
            and not _is_boilerplate_notice(line)
        ):
            return line[:120]
    return "Untitled Sheet"


def _is_valid_sheet_sequence(sequence: str) -> bool:
    token = sequence.upper()
    digit_count = sum(1 for ch in token if ch.isdigit())
    if "." in token:
        return digit_count >= 3
    return digit_count >= 3


def _sheet_id_score(prefix: str, sequence: str, line: str) -> int:
    score = 0
    if prefix in DISCIPLINE_PREFIX_TO_TRADE and DISCIPLINE_PREFIX_TO_TRADE[prefix] != "other":
        score += 4
    elif prefix in DISCIPLINE_PREFIX_TO_TRADE:
        score += 1

    if "." in sequence:
        score += 3
    else:
        score += min(sum(1 for ch in sequence if ch.isdigit()), 4)

    if SHEET_ID_LINE_HINTS_RE.search(line):
        score += 3
    if line.strip().startswith(prefix):
        score += 1
    return score


def _extract_complex_sheet_id_candidates(line: str) -> list[str]:
    candidates: list[str] = []
    for match in COMPLEX_SHEET_ID_RE.finditer(line.upper()):
        token = match.group(1)
        parsed = _parse_complex_sheet_id(token)
        if parsed is None:
            continue
        _, _, normalized = parsed
        candidates.append(normalized)
    return candidates


def _parse_complex_sheet_id(token: str) -> tuple[str, str, str] | None:
    parts = token.split("-")
    if len(parts) < 3:
        return None

    # Ensure this looks like a facility-prefixed sheet id, not arbitrary hyphen text.
    if not any(any(ch.isdigit() for ch in part) for part in parts[:-1]):
        return None

    tail = parts[-1]
    tail_match = re.fullmatch(r"([A-Z]{1,2})(\d{1,4}(?:\.\d{1,2})?[A-Z]?)", tail)
    if not tail_match:
        return None

    prefix = tail_match.group(1)
    sequence = tail_match.group(2)
    if prefix not in ALLOWED_PREFIXES:
        return None
    return prefix, sequence, token


def _complex_sheet_id_score(candidate: str, line: str) -> int:
    score = 9
    if SHEET_ID_LINE_HINTS_RE.search(line):
        score += 3
    if line.strip().upper().startswith(candidate):
        score += 2
    return score


def _looks_like_grid_label(line: str) -> bool:
    compact = "".join(ch for ch in line if ch.isalnum() or ch.isspace()).strip()
    parts = [p for p in compact.split() if p]
    if 2 <= len(parts) <= 8 and all(len(p) <= 2 for p in parts):
        if all(p.isalpha() for p in parts) or all(p.isdigit() for p in parts):
            return True
    return False


def _is_metadata_label(line: str) -> bool:
    normalized = " ".join(line.upper().split())
    if SCALE_METADATA_RE.search(normalized):
        return True
    metadata_terms = {
        "DRAWING NO",
        "DRAWING NO.",
        "SHEET NO",
        "SCALE",
        "DATE",
        "TITLE BLOCK",
        "PROJECT NO",
        "SUBMITTED",
        "SUBMITTED:",
    }
    if normalized in metadata_terms:
        return True
    metadata_fragments = (
        "SHEET SIZE",
        "PROJECT NO",
        "MSFC-FORM",
        "REV.",
        "DRAWN BY",
        "CHECKED BY",
        "NASA",
    )
    return any(fragment in normalized for fragment in metadata_fragments)


def _is_boilerplate_notice(line: str) -> bool:
    normalized = " ".join(line.upper().split())
    blocked_phrases = (
        "CHANGES TO THIS DRAWING SHALL BE MADE",
        "DO NOT SCALE DRAWING",
        "ALL RIGHTS RESERVED",
        "DRAWING IS INCOMPLETE",
        "THIS DRAWING WAS DESIGNED TO BE PRINTED AT",
    )
    return any(phrase in normalized for phrase in blocked_phrases)


def _build_overrides_by_index(
    pages: list[LoadedPage], sheet_overrides: list[dict[str, object]]
) -> dict[int, dict[str, object]]:
    by_page_index: dict[int, dict[str, object]] = {}
    fallback: list[dict[str, object]] = []

    for override in sheet_overrides:
        raw_page = override.get("source_page_index")
        page_index = _parse_source_page_index(raw_page)
        if page_index is None:
            fallback.append(override)
            continue
        by_page_index[page_index] = override

    if fallback:
        available_pages = [page.page_index for page in pages if page.page_index not in by_page_index]
        for override, page_index in zip(fallback, available_pages):
            by_page_index[page_index] = override
    return by_page_index


def _parse_source_page_index(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    value: int | None = None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            return None

    if value is None:
        return None
    if value < 1:
        return None
    return value - 1
