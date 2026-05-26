from __future__ import annotations

import logging
import re
import warnings
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedPage:
    page_index: int
    source_pdf: str
    text: str


LAYOUT_WARNING_LOGGER = "pypdf._text_extraction._layout_mode._fixed_width_page"


def load_pdf_pages(pdf_path: str) -> tuple[list[LoadedPage], list[str]]:
    """
    Loads text from each PDF page.

    Returns:
    - list of LoadedPage
    - list of issues
    """
    issues: list[str] = []
    path = Path(pdf_path)
    if not path.exists():
        return [], [f"PDF not found: {pdf_path}"]

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return [], [
            "pypdf is not installed. Unable to read vector text from PDF. "
            "Install dependencies or provide OCR text."
        ]

    pages: list[LoadedPage] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pragma: no cover - environment dependent
        return [], [f"Failed to open PDF '{pdf_path}': {exc}"]

    for idx, page in enumerate(reader.pages):
        text = ""
        try:
            plain_text = page.extract_text(extraction_mode="plain") or ""
            layout_logger = logging.getLogger(LAYOUT_WARNING_LOGGER)
            previous_level = layout_logger.level
            layout_logger.setLevel(logging.ERROR)
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Rotated text discovered.*")
                    layout_text = page.extract_text(
                        extraction_mode="layout",
                        layout_mode_space_vertically=False,
                    ) or ""
            finally:
                layout_logger.setLevel(previous_level)
            text = _choose_best_extracted_text(plain_text=plain_text, layout_text=layout_text)
        except Exception:
            issues.append(f"Text extraction failed on page {idx + 1} in {pdf_path}.")
        pages.append(LoadedPage(page_index=idx, source_pdf=str(path), text=text))

    if not pages:
        issues.append(f"No pages detected in PDF: {pdf_path}")
    return pages, issues


def _choose_best_extracted_text(plain_text: str, layout_text: str) -> str:
    plain = plain_text or ""
    layout = layout_text or ""
    if not plain:
        return layout
    if not layout:
        return plain

    plain_score = _text_quality_score(plain)
    layout_score = _text_quality_score(layout)
    return layout if layout_score > plain_score else plain


def _text_quality_score(text: str) -> int:
    if not text:
        return 0

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    token_re = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]{1,}")
    tokens = token_re.findall(text.upper())
    alpha_tokens = [token for token in tokens if any(ch.isalpha() for ch in token)]

    score = 0
    score += len(alpha_tokens) * 2
    score += len(lines)
    score += min(len(set(alpha_tokens)), 100)

    if re.search(r"\b[A-Z]{1,2}\d{1,4}(?:\.\d{1,2})?[A-Z]?\b", text.upper()):
        score += 14
    if re.search(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{1,12}){2,}\b", text.upper()):
        score += 14
    if "SCALE" in text.upper():
        score += 4
    return score
