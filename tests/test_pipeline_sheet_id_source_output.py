from ai_estimator.extractors.sheet_classifier import ClassifiedSheet
from ai_estimator.pipeline import run_pipeline


def test_pipeline_emits_sheet_id_source_field(monkeypatch):
    def _fake_load_pdf_pages(_: str):
        return [], []

    def _fake_classify_sheets(*, pages, sheet_overrides):  # type: ignore[no-untyped-def]
        return [
            ClassifiedSheet(
                sheet_id="A101",
                sheet_id_source="override",
                title="First Floor Plan",
                sheet_type="plan",
                trade="architectural",
                confidence=0.9,
                source_page_index=0,
                source_pdf="x.pdf",
            )
        ]

    monkeypatch.setattr("ai_estimator.pipeline.load_pdf_pages", _fake_load_pdf_pages)
    monkeypatch.setattr("ai_estimator.pipeline.classify_sheets", _fake_classify_sheets)

    payload = run_pipeline(
        pdf_paths=["C:/does/not/matter.pdf"],
        analysis_mode="auto",
        selected_trades=[],
        validate_schema=False,
    )
    assert payload["sheets_detected"][0]["sheet_id_source"] == "override"

