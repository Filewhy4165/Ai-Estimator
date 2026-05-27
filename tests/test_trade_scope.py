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


def test_scope_keeps_multiple_trades_from_same_sheet():
    sheets = [
        ClassifiedSheet(
            sheet_id="A101",
            sheet_id_source="detected",
            title="Combined plan",
            sheet_type="plan",
            trade="architectural",
            confidence=0.91,
            source_page_index=0,
            source_pdf="x.pdf",
        ),
        ClassifiedSheet(
            sheet_id="A101",
            sheet_id_source="detected",
            title="Combined plan",
            sheet_type="plan",
            trade="mechanical_hvac",
            confidence=0.9,
            source_page_index=0,
            source_pdf="x.pdf",
        ),
    ]

    scope = resolve_trade_scope(sheets=sheets, requested_mode="all", requested_trades=[])
    assert scope.detected_trades == ["architectural", "mechanical_hvac"]
    assert scope.analyzed_trades == ["architectural", "mechanical_hvac"]
    assert sorted({(row["sheet"], row["trade"]) for row in scope.sheet_trade_map}) == [
        ("A101", "architectural"),
        ("A101", "mechanical_hvac"),
    ]


def test_scope_dedupes_same_sheet_trade_by_highest_confidence():
    sheets = [
        ClassifiedSheet(
            sheet_id="M201",
            sheet_id_source="detected",
            title="Mechanical",
            sheet_type="plan",
            trade="mechanical_hvac",
            confidence=0.62,
            source_page_index=0,
            source_pdf="x.pdf",
        ),
        ClassifiedSheet(
            sheet_id="M201",
            sheet_id_source="detected",
            title="Mechanical",
            sheet_type="plan",
            trade="mechanical_hvac",
            confidence=0.88,
            source_page_index=0,
            source_pdf="x.pdf",
        ),
    ]

    scope = resolve_trade_scope(sheets=sheets, requested_mode="auto", requested_trades=[])
    assert scope.detected_trades == ["mechanical_hvac"]
    assert scope.analyzed_trades == ["mechanical_hvac"]
    assert scope.sheet_trade_map == [{"sheet": "M201", "trade": "mechanical_hvac", "confidence": 0.88}]
