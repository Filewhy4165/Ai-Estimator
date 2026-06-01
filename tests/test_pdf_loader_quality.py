from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from ai_estimator.extractors.pdf_loader import (
    _choose_best_extracted_text,
    _text_quality_score,
    load_pdf_pages,
)


def test_choose_best_extracted_text_prefers_layout_when_richer():
    plain = "\n".join(
        [
            "NASA",
            "C D E F G",
            "A B",
        ]
    )
    layout = "\n".join(
        [
            "FAC-BT-4476-A1",
            "FLOOR PLAN, SCHEDULES AND NOTES",
            "SCALE: 1/8\" = 1'-0\"",
        ]
    )
    assert _choose_best_extracted_text(plain, layout) == layout


def test_choose_best_extracted_text_keeps_plain_when_layout_is_weaker():
    plain = "\n".join(
        [
            "A101 FIRST FLOOR PLAN",
            "SCALE: 1/8\" = 1'-0\"",
            "ARCHITECTURAL NOTES",
        ]
    )
    layout = "\n".join(
        [
            "NASA",
            "C D E F G",
            "A B",
        ]
    )
    assert _choose_best_extracted_text(plain, layout) == plain


def test_text_quality_score_rewards_sheet_id_signals():
    weak = "NASA\nC D E F G\nA B"
    strong = "FAC-AZ-4556-E1\nFLOOR PLANS, NOTES AND LEGEND\nSCALE: 1/8\" = 1'-0\""
    assert _text_quality_score(strong) > _text_quality_score(weak)


def test_load_pdf_pages_extracts_basic_vector_linework(tmp_path: Path):
    pdf_path = tmp_path / "vector.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b"10 10 m 110 10 l S\n20 20 30 40 re S\n")
    writer.pages[0][NameObject("/Contents")] = stream
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    pages, issues = load_pdf_pages(str(pdf_path))

    assert issues == []
    assert len(pages) == 1
    assert pages[0].width == 200
    assert pages[0].height == 100
    primitives = pages[0].vector_primitives
    assert [item["kind"] for item in primitives] == ["line", "rectangle"]
    assert primitives[0]["length_pdf_units"] == 100
    assert primitives[1]["perimeter_pdf_units"] == 140

