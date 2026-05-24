from service.request_parsing import normalize_notes, parse_sheet_overrides_json


def test_parse_sheet_overrides_json_valid():
    raw = '[{"sheet_id":"A101","title":"Floor Plan","source_page_index":2},{"sheet_id":"S201","title":"Foundation Plan"}]'
    parsed = parse_sheet_overrides_json(raw)
    assert parsed == [
        {"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 2},
        {"sheet_id": "S201", "title": "Foundation Plan"},
    ]


def test_parse_sheet_overrides_json_empty_returns_none():
    assert parse_sheet_overrides_json("") is None
    assert parse_sheet_overrides_json("   ") is None
    assert parse_sheet_overrides_json(None) is None


def test_normalize_notes():
    assert normalize_notes(None) is None
    assert normalize_notes("   ") is None
    assert normalize_notes(" Hello ") == "Hello"


def test_parse_sheet_overrides_json_invalid_page_index():
    raw = '[{"sheet_id":"A101","title":"Floor Plan","source_page_index":"zero"}]'
    try:
        parse_sheet_overrides_json(raw)
    except ValueError as exc:
        assert "source_page_index" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid source_page_index")


def test_parse_sheet_overrides_json_invalid_sheet_id_without_title_becomes_title():
    raw = '[{"sheet_id":"FLOOR PLANS, SCHEDULE AND NOTES","source_page_index":4}]'
    parsed = parse_sheet_overrides_json(raw)
    assert parsed == [
        {
            "sheet_id": "",
            "title": "FLOOR PLANS, SCHEDULE AND NOTES",
            "source_page_index": 4,
        }
    ]


def test_parse_sheet_overrides_json_invalid_sheet_id_with_title_raises():
    raw = '[{"sheet_id":"FLOOR PLANS, SCHEDULE AND NOTES","title":"Actual Title","source_page_index":4}]'
    try:
        parse_sheet_overrides_json(raw)
    except ValueError as exc:
        assert "sheet_id is invalid" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid sheet_id with explicit title")
