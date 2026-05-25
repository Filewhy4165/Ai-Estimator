from ai_estimator.extractors.geometry import extract_geometry
from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


def test_extract_geometry_includes_fixture_and_equipment_tags():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="WC-1 WC-1 LAV-3 UR-2 AHU-1 SAT-2 DSW-301",
        )
    ]
    sheets = [
        ClassifiedSheet(
            sheet_id="P101",
            title="Plumbing Plan",
            sheet_type="plan",
            trade="plumbing",
            confidence=0.9,
            source_page_index=0,
            source_pdf="x.pdf",
        )
    ]

    geometry, issues = extract_geometry(pages, sheets)
    assert issues == []

    fixture_tags = sorted(item["properties"]["tag"] for item in geometry["fixtures"])
    equipment_tags = sorted(item["properties"]["tag"] for item in geometry["equipment"])
    assert fixture_tags == ["LAV-3", "UR-2", "WC-1"]
    assert equipment_tags == ["AHU-1", "DSW-301", "SAT-2"]


def test_extract_geometry_ignores_unmapped_symbol_prefixes():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="P-1 P-2 X-99 NOTE-1",
        )
    ]
    sheets = [
        ClassifiedSheet(
            sheet_id="A101",
            title="Plan",
            sheet_type="plan",
            trade="architectural",
            confidence=0.9,
            source_page_index=0,
            source_pdf="x.pdf",
        )
    ]

    geometry, _ = extract_geometry(pages, sheets)
    assert geometry["fixtures"] == []
    assert geometry["equipment"] == []
