from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedPage:
    page_index: int
    source_pdf: str
    text: str


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
            text = page.extract_text() or ""
        except Exception:
            issues.append(f"Text extraction failed on page {idx + 1} in {pdf_path}.")
        pages.append(LoadedPage(page_index=idx, source_pdf=str(path), text=text))

    if not pages:
        issues.append(f"No pages detected in PDF: {pdf_path}")
    return pages, issues

