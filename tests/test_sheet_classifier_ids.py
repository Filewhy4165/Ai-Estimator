from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import classify_sheets


def test_sheet_id_supports_single_digit_dotted_form():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "SHEET A1.01",
                    "FLOOR PLAN",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id == "A1.01"
    assert sheets[0].sheet_type == "plan"
    assert sheets[0].trade == "architectural"


def test_sheet_id_supports_facility_prefixed_hyphenated_form():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "FAC-AZ-4556-E1",
                    "FLOOR PLANS, NOTES AND LEGEND",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id == "FAC-AZ-4556-E1"
    assert sheets[0].sheet_type == "plan"
    assert sheets[0].trade == "electrical"


def test_sheet_id_does_not_accept_short_single_digit_standard_id():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "A1",
                    "GENERAL NOTES",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id.startswith("UNMAPPED_")


def test_sheet_id_uses_building_context_for_short_form():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "BUILDING 4476",
                    "A1 FLOOR PLAN, SCHEDULES AND NOTES",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id == "FAC-4476-A1"
    assert sheets[0].sheet_type == "plan"
    assert sheets[0].trade == "architectural"
    assert sheets[0].confidence == 0.62


def test_sheet_id_ignores_trailing_short_token_in_notes():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "BUILDING 4476",
                    "MATCH EXISTING PLAN DIMENSIONS. INSTALL NEW TOILET PARTITIONS..  A4.",
                    "GENERAL NOTES",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id.startswith("UNMAPPED_")


def test_sheet_id_short_fallback_skips_other_prefixes():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "BUILDING 4476",
                    "X1",
                    "GENERAL NOTES",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id.startswith("UNMAPPED_")


def test_sheet_id_short_fallback_confidence_is_capped_even_with_strong_keywords():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "BUILDING 4476",
                    "E2 ELECTRICAL POWER LIGHTING PANELBOARD ONE-LINE PLAN",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id == "FAC-4476-E2"
    assert sheets[0].confidence == 0.62

