from ai_estimator.pipeline import run_pipeline


def test_pipeline_includes_spec_context_when_profiles_provided():
    payload = run_pipeline(
        pdf_paths=["C:/does/not/exist.pdf"],
        analysis_mode="auto",
        selected_trades=[],
        spec_profiles=[
            {
                "spec_id": "spec-a",
                "organization": "NASA",
                "agency": "NASA",
                "standard_name": "TSRC",
                "project_type": "federal",
                "detected_standard_refs": ["NFPA 70"],
                "detected_trade_hints": ["electrical"],
                "is_public": True,
            }
        ],
        validate_schema=False,
    )
    spec_context = payload.get("spec_context", {})
    assert isinstance(spec_context, dict)
    assert spec_context.get("authority_order") == ["drawings", "specifications", "assumptions"]
    assert spec_context.get("applied_spec_count") == 1
