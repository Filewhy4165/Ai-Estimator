from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.scale_analyzer import analyze_scales
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


def _sheet(*, page_index: int, sheet_id: str) -> ClassifiedSheet:
    return ClassifiedSheet(
        sheet_id=sheet_id,
        sheet_id_source="detected",
        title="Test",
        sheet_type="plan",
        trade="architectural",
        confidence=0.9,
        source_page_index=page_index,
        source_pdf="x.pdf",
    )


def test_scale_analysis_collapses_duplicate_sheet_ids_and_keeps_detected_scale():
    pages = [
        LoadedPage(page_index=0, source_pdf="x.pdf", text='SCALE: 1/8" = 1\'-0"'),
        LoadedPage(page_index=1, source_pdf="x.pdf", text="No measurable scale here."),
    ]
    sheets = [_sheet(page_index=0, sheet_id="A101"), _sheet(page_index=1, sheet_id="A101")]

    payload, issues = analyze_scales(pages, sheets)
    rows = payload.get("by_sheet", [])

    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["sheet_id"] == "A101"
    assert rows[0]["detected_scale"] == '1/8" = 1\'-0"'
    assert issues == []


def test_scale_analysis_undetected_issue_lists_sheet_once_when_duplicate_pages():
    pages = [
        LoadedPage(page_index=0, source_pdf="x.pdf", text="No scale."),
        LoadedPage(page_index=1, source_pdf="x.pdf", text="Still no scale."),
    ]
    sheets = [_sheet(page_index=0, sheet_id="A101"), _sheet(page_index=1, sheet_id="A101")]

    payload, issues = analyze_scales(pages, sheets)
    rows = payload.get("by_sheet", [])

    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["sheet_id"] == "A101"
    assert rows[0]["detected_scale"] is None
    assert len(issues) == 1
    assert issues[0].count("A101") == 1
