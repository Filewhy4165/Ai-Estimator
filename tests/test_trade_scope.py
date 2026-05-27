from ai_estimator.extractors.sheet_classifier import ClassifiedSheet
from ai_estimator.trade_scope import resolve_trade_scope


def test_selected_scope_only_keeps_requested():
    sheets = [
        ClassifiedSheet(
            sheet_id="A101",
            sheet_id_source="detected",
            title="Floor Plan",
            sheet_type="plan",
            trade="architectural",
            confidence=0.9,
            source_page_index=0,
            source_pdf="x.pdf",
        ),
        ClassifiedSheet(
            sheet_id="M201",
            sheet_id_source="detected",
            title="Mechanical Plan",
            sheet_type="plan",
            trade="mechanical_hvac",
            confidence=0.9,
            source_page_index=1,
            source_pdf="x.pdf",
        ),
    ]

    scope = resolve_trade_scope(
        sheets=sheets,
        requested_mode="selected",
        requested_trades=["architectural"],
    )
    assert scope.analyzed_trades == ["architectural"]
    assert scope.detected_trades == ["architectural", "mechanical_hvac"]


def test_auto_scope_skips_low_confidence():
    sheets = [
        ClassifiedSheet(
            sheet_id="X001",
            sheet_id_source="detected",
            title="Unknown",
            sheet_type="other",
            trade="other",
            confidence=0.2,
            source_page_index=0,
            source_pdf="x.pdf",
        )
    ]
    scope = resolve_trade_scope(sheets=sheets, requested_mode="auto", requested_trades=[])
    assert scope.analyzed_trades == []
    assert len(scope.skipped_trades) == 1
