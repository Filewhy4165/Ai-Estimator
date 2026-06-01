from __future__ import annotations

import logging
import math
import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LoadedPage:
    page_index: int
    source_pdf: str
    text: str
    width: float | None = None
    height: float | None = None
    vector_primitives: list[dict[str, object]] = field(default_factory=list)


LAYOUT_WARNING_LOGGER = "pypdf._text_extraction._layout_mode._fixed_width_page"
DEFAULT_MAX_VECTOR_PRIMITIVES_PER_PAGE = 5000


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
        from pypdf.generic import ContentStream  # type: ignore
    except Exception:
        return [], [
            "pypdf is not installed. Unable to read text/vector content from PDF. "
            "Install dependencies or provide OCR text."
        ]

    pages: list[LoadedPage] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pragma: no cover - environment dependent
        return [], [f"Failed to open PDF '{pdf_path}': {exc}"]

    for idx, page in enumerate(reader.pages):
        text = ""
        width, height = _extract_page_size(page)
        vector_primitives: list[dict[str, object]] = []
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
        try:
            vector_primitives = _extract_vector_primitives(
                page,
                reader=reader,
                content_stream_cls=ContentStream,
                max_primitives=_resolve_max_vector_primitives_per_page(),
            )
        except Exception:
            issues.append(f"Vector extraction failed on page {idx + 1} in {pdf_path}.")
        pages.append(
            LoadedPage(
                page_index=idx,
                source_pdf=str(path),
                text=text,
                width=width,
                height=height,
                vector_primitives=vector_primitives,
            )
        )

    if not pages:
        issues.append(f"No pages detected in PDF: {pdf_path}")
    return pages, issues


def _extract_page_size(page: Any) -> tuple[float | None, float | None]:
    try:
        box = page.mediabox
        return round(float(box.width), 4), round(float(box.height), 4)
    except Exception:
        return None, None


def _resolve_max_vector_primitives_per_page() -> int:
    raw = os.environ.get("AI_ESTIMATOR_MAX_VECTOR_PRIMITIVES_PER_PAGE", "").strip()
    if not raw:
        return DEFAULT_MAX_VECTOR_PRIMITIVES_PER_PAGE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_VECTOR_PRIMITIVES_PER_PAGE
    return max(100, min(value, 50000))


def _extract_vector_primitives(
    page: Any,
    *,
    reader: Any,
    content_stream_cls: Any,
    max_primitives: int,
) -> list[dict[str, object]]:
    contents = page.get_contents()
    if contents is None:
        return []

    stream = content_stream_cls(contents, reader)
    primitives: list[dict[str, object]] = []
    ctm: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack: list[tuple[float, float, float, float, float, float]] = []
    current_point: tuple[float, float] | None = None
    subpath_start: tuple[float, float] | None = None
    line_width = 1.0

    for operands, operator_raw in stream.operations:
        operator = _operator_token(operator_raw)
        if operator == "q":
            ctm_stack.append(ctm)
            continue
        if operator == "Q":
            ctm = ctm_stack.pop() if ctm_stack else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            continue
        if operator == "cm" and len(operands) >= 6:
            matrix = tuple(_num(value) for value in operands[:6])
            ctm = _matrix_multiply(ctm, matrix)  # type: ignore[arg-type]
            continue
        if operator == "w" and operands:
            line_width = max(0.0, _num(operands[0], default=line_width))
            continue
        if operator == "m" and len(operands) >= 2:
            current_point = _transform_point(ctm, _num(operands[0]), _num(operands[1]))
            subpath_start = current_point
            continue
        if operator == "l" and len(operands) >= 2:
            next_point = _transform_point(ctm, _num(operands[0]), _num(operands[1]))
            if current_point is not None:
                primitive = _line_primitive(
                    current_point,
                    next_point,
                    line_width=line_width,
                    source_operator="l",
                )
                if primitive is not None:
                    primitives.append(primitive)
            current_point = next_point
            if len(primitives) >= max_primitives:
                break
            continue
        if operator == "h":
            if current_point is not None and subpath_start is not None:
                primitive = _line_primitive(
                    current_point,
                    subpath_start,
                    line_width=line_width,
                    source_operator="h",
                )
                if primitive is not None:
                    primitives.append(primitive)
                current_point = subpath_start
            if len(primitives) >= max_primitives:
                break
            continue
        if operator == "re" and len(operands) >= 4:
            x = _num(operands[0])
            y = _num(operands[1])
            width = _num(operands[2])
            height = _num(operands[3])
            primitive = _rectangle_primitive(
                [
                    _transform_point(ctm, x, y),
                    _transform_point(ctm, x + width, y),
                    _transform_point(ctm, x + width, y + height),
                    _transform_point(ctm, x, y + height),
                ],
                line_width=line_width,
            )
            if primitive is not None:
                primitives.append(primitive)
            current_point = _transform_point(ctm, x, y)
            subpath_start = current_point
            if len(primitives) >= max_primitives:
                break

    return primitives


def _operator_token(operator: Any) -> str:
    if isinstance(operator, bytes):
        return operator.decode("latin-1", errors="ignore")
    return str(operator)


def _num(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _matrix_multiply(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        (a1 * a2) + (c1 * b2),
        (b1 * a2) + (d1 * b2),
        (a1 * c2) + (c1 * d2),
        (b1 * c2) + (d1 * d2),
        (a1 * e2) + (c1 * f2) + e1,
        (b1 * e2) + (d1 * f2) + f1,
    )


def _transform_point(
    matrix: tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return ((a * x) + (c * y) + e, (b * x) + (d * y) + f)


def _line_primitive(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    line_width: float,
    source_operator: str,
) -> dict[str, object] | None:
    x1, y1 = start
    x2, y2 = end
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 0.01:
        return None
    return {
        "kind": "line",
        "source_operator": source_operator,
        "points": [[_round_coord(x1), _round_coord(y1)], [_round_coord(x2), _round_coord(y2)]],
        "bbox": _bbox([start, end]),
        "line_width": _round_coord(line_width),
        "length_pdf_units": round(length, 4),
    }


def _rectangle_primitive(
    points: list[tuple[float, float]],
    *,
    line_width: float,
) -> dict[str, object] | None:
    if len(points) != 4:
        return None
    edge_lengths = [
        math.hypot(points[(index + 1) % 4][0] - points[index][0], points[(index + 1) % 4][1] - points[index][1])
        for index in range(4)
    ]
    perimeter = sum(edge_lengths)
    if perimeter <= 0.01:
        return None
    return {
        "kind": "rectangle",
        "source_operator": "re",
        "points": [[_round_coord(x), _round_coord(y)] for x, y in points],
        "bbox": _bbox(points),
        "line_width": _round_coord(line_width),
        "perimeter_pdf_units": round(perimeter, 4),
        "edge_lengths_pdf_units": [round(value, 4) for value in edge_lengths],
    }


def _bbox(points: list[tuple[float, float]]) -> list[float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [_round_coord(min(xs)), _round_coord(min(ys)), _round_coord(max(xs)), _round_coord(max(ys))]


def _round_coord(value: float) -> float:
    return round(float(value), 4)


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
