from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import classify_sheets


def test_sheet_overrides_use_source_page_index():
    pages = [
        LoadedPage(page_index=0, source_pdf="x.pdf", text="A101 FIRST FLOOR PLAN"),
        LoadedPage(page_index=1, source_pdf="x.pdf", text="S201 FOUNDATION PLAN"),
        LoadedPage(page_index=2, source_pdf="x.pdf", text="M301 HVAC PLAN"),
    ]
    overrides = [
        {"source_page_index": 3, "sheet_id": "P401", "title": "PLUMBING PLAN"},
    ]
    sheets = classify_sheets(pages, overrides)
    third = next(s for s in sheets if s.source_page_index == 2)
    assert third.sheet_id == "P401"
    assert third.title == "PLUMBING PLAN"


def test_sheet_overrides_fallback_order_when_page_index_missing():
    pages = [
        LoadedPage(page_index=0, source_pdf="x.pdf", text="A101 FIRST FLOOR PLAN"),
        LoadedPage(page_index=1, source_pdf="x.pdf", text="S201 FOUNDATION PLAN"),
    ]
    overrides = [{"sheet_id": "A100", "title": "COVER SHEET"}]
    sheets = classify_sheets(pages, overrides)
    first = next(s for s in sheets if s.source_page_index == 0)
    assert first.sheet_id == "A100"
    assert first.title == "COVER SHEET"

