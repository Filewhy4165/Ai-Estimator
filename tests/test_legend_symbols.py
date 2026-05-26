from ai_estimator.extractors.legend_symbols import extract_legend_and_symbols
from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


def _sheet(*, page_index: int, sheet_id: str) -> ClassifiedSheet:
    return ClassifiedSheet(
        sheet_id=sheet_id,
        title="Test",
        sheet_type="plan",
        trade="architectural",
        confidence=0.9,
        source_page_index=page_index,
        source_pdf="x.pdf",
    )


def test_legend_extraction_collapses_duplicate_sheet_ids_and_merges_entries():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text=(
                "LEGEND\n"
                "P-1  WATER CLOSET\n"
                "P-2  URINAL\n"
                "SAT-1\n"
            ),
        ),
        LoadedPage(
            page_index=1,
            source_pdf="x.pdf",
            text=(
                "SYMBOL LEGEND\n"
                "P-2  URINAL\n"
                "P-3  LAVATORY\n"
                "SAT-1\n"
            ),
        ),
    ]
    sheets = [_sheet(page_index=0, sheet_id="A101"), _sheet(page_index=1, sheet_id="A101")]

    payload, issues = extract_legend_and_symbols(pages, sheets)
    legends = payload.get("legends_by_sheet", [])
    unknown_symbols = payload.get("unknown_symbols", [])

    assert issues == []
    assert isinstance(legends, list)
    assert len(legends) == 1
    assert legends[0]["sheet_id"] == "A101"

    entries = legends[0]["entries"]
    symbols = sorted(item["symbol"] for item in entries)
    assert symbols == ["P-1", "P-2", "P-3"]

    sat_rows = [row for row in unknown_symbols if row.get("symbol") == "SAT-1"]
    assert len(sat_rows) == 1
    assert sat_rows[0]["sheet_id"] == "A101"
