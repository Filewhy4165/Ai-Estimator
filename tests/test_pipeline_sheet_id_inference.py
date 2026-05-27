from ai_estimator.extractors.sheet_classifier import ClassifiedSheet
from ai_estimator.pipeline import _collect_sheet_id_inference_issues, _normalize_issues


def test_collect_sheet_id_inference_issues_returns_warning_with_source_sheets():
    sheets = [
        ClassifiedSheet(
            sheet_id="FAC-4476-A1",
            sheet_id_source="inferred_facility_short",
            title="Floor Plan",
            sheet_type="plan",
            trade="architectural",
            confidence=0.62,
            source_page_index=0,
            source_pdf="x.pdf",
        ),
        ClassifiedSheet(
            sheet_id="A101",
            sheet_id_source="detected",
            title="First Floor Plan",
            sheet_type="plan",
            trade="architectural",
            confidence=0.88,
            source_page_index=1,
            source_pdf="x.pdf",
        ),
        ClassifiedSheet(
            sheet_id="FAC-4583-E1",
            sheet_id_source="inferred_facility_short",
            title="Electrical Plan",
            sheet_type="plan",
            trade="electrical",
            confidence=0.62,
            source_page_index=2,
            source_pdf="x.pdf",
        ),
    ]

    issues = _collect_sheet_id_inference_issues(sheets)
    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert issues[0]["source_sheets"] == ["FAC-4476-A1", "FAC-4583-E1"]


def test_collect_sheet_id_inference_issues_returns_empty_when_none():
    sheets = [
        ClassifiedSheet(
            sheet_id="A101",
            sheet_id_source="detected",
            title="First Floor Plan",
            sheet_type="plan",
            trade="architectural",
            confidence=0.88,
            source_page_index=0,
            source_pdf="x.pdf",
        )
    ]
    assert _collect_sheet_id_inference_issues(sheets) == []


def test_normalize_issues_preserves_structured_issue_fields():
    raw = [
        {
            "message": "Inferred sheet IDs require review.",
            "severity": "warning",
            "source_sheets": ["FAC-4476-A1", "FAC-4476-A1"],
        },
        {
            "message": "Inferred sheet IDs require review.",
            "severity": "warning",
            "source_sheets": ["FAC-4476-A1"],
        },
        "  Generic warning from extractor. ",
    ]
    normalized = _normalize_issues(raw)
    assert normalized == [
        {
            "message": "Inferred sheet IDs require review.",
            "severity": "warning",
            "source_sheets": ["FAC-4476-A1"],
        },
        {"message": "Generic warning from extractor.", "severity": "warning"},
    ]

