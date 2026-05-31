from ai_estimator.spec_intel import (
    build_spec_context,
    build_spec_issues,
    build_submittal_queries,
    extract_standard_references,
    extract_trade_hints,
)


def test_extract_standard_references_and_trade_hints():
    text = """
    Mechanical system shall comply with ASHRAE 90.1 and NFPA 70.
    Structural concrete shall comply with ACI 318 and ASTM C150.
    """
    refs = extract_standard_references(text)
    trades = extract_trade_hints(text)

    assert "ASHRAE 90.1" in refs
    assert "NFPA 70" in refs
    assert "ACI 318" in refs
    assert "ASTM C150" in refs
    assert "mechanical_hvac" in trades
    assert "structural" in trades


def test_build_spec_context_and_issue_when_trade_missing_from_drawings():
    profiles = [
        {
            "spec_id": "spec-1",
            "organization": "NASA",
            "agency": "NASA",
            "standard_name": "TSRC",
            "project_type": "facility",
            "detected_standard_refs": ["NFPA 70"],
            "detected_trade_hints": ["electrical"],
            "is_public": True,
        }
    ]
    context = build_spec_context(
        spec_profiles=profiles,
        detected_trades=["plumbing"],
    )
    issues = build_spec_issues(context)

    assert context["authority_order"] == ["drawings", "specifications", "assumptions"]
    assert context["missing_from_drawings"] == ["electrical"]
    assert issues
    assert issues[0]["severity"] == "warning"


def test_build_submittal_queries_from_specs():
    profiles = [
        {
            "standard_name": "NASA TSRC",
            "detected_standard_refs": ["ASTM C150"],
            "detected_trade_hints": ["structural"],
        }
    ]
    queries = build_submittal_queries(spec_profiles=profiles, max_queries=10)
    assert queries
    assert any("ASTM C150" in query for query in queries)
