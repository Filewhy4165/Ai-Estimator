from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import classify_sheets


def test_sheet_title_prefers_plan_line_over_scale_line():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "C D E F G",
                    "SCALE: 1/8\" = 1'-0\"",
                    "A102 PLUMBING DEMOLITION PLAN",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].sheet_id == "A102"
    assert sheets[0].title == "A102 PLUMBING DEMOLITION PLAN"


def test_sheet_title_does_not_fall_back_to_scale_metadata():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="\n".join(
                [
                    "SCALE: 1/8\" = 1'-0\"",
                    "DRAWN BY: TESTER",
                    "CHECKED BY: REVIEWER",
                ]
            ),
        )
    ]
    sheets = classify_sheets(pages, sheet_overrides=None)
    assert len(sheets) == 1
    assert sheets[0].title == "Untitled Sheet"
