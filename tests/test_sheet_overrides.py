import json

from ai_estimator.pipeline import load_sheet_overrides
from ai_estimator.sheet_overrides import normalize_sheet_overrides_items, parse_sheet_overrides_json


def test_parse_sheet_overrides_json_valid():
    raw = '[{"sheet_id":"A101","title":"Floor Plan","source_page_index":2}]'
    parsed = parse_sheet_overrides_json(raw)
    assert parsed == [{"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 2}]


def test_normalize_sheet_overrides_items_invalid_sheet_id_without_title_becomes_title():
    loaded = [{"sheet_id": "FLOOR PLANS, SCHEDULE AND NOTES", "source_page_index": 4}]
    parsed = normalize_sheet_overrides_items(loaded)
    assert parsed == [
        {
            "sheet_id": "",
            "title": "FLOOR PLANS, SCHEDULE AND NOTES",
            "source_page_index": 4,
        }
    ]


def test_normalize_sheet_overrides_items_invalid_sheet_id_with_title_raises():
    loaded = [
        {
            "sheet_id": "FLOOR PLANS, SCHEDULE AND NOTES",
            "title": "Actual Title",
            "source_page_index": 4,
        }
    ]
    try:
        normalize_sheet_overrides_items(loaded)
    except ValueError as exc:
        assert "sheet_id is invalid" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid sheet_id with explicit title")


def test_load_sheet_overrides_sanitizes_invalid_sheet_id(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps([{"sheet_id": "FLOOR PLANS, SCHEDULE AND NOTES", "source_page_index": 3}]),
        encoding="utf-8",
    )
    parsed = load_sheet_overrides(str(path))
    assert parsed == [
        {
            "sheet_id": "",
            "title": "FLOOR PLANS, SCHEDULE AND NOTES",
            "source_page_index": 3,
        }
    ]


def test_load_sheet_overrides_invalid_page_index_raises(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps([{"sheet_id": "A101", "title": "Floor Plan", "source_page_index": "zero"}]),
        encoding="utf-8",
    )
    try:
        load_sheet_overrides(str(path))
    except ValueError as exc:
        assert "source_page_index" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid source_page_index")


def test_normalize_sheet_overrides_uses_current_sheet_id_when_sheet_id_missing():
    loaded = [{"current_sheet_id": "A101", "title": "Floor Plan", "source_page_index": 2}]
    parsed = normalize_sheet_overrides_items(loaded)
    assert parsed == [
        {
            "sheet_id": "A101",
            "title": "Floor Plan",
            "source_page_index": 2,
        }
    ]


def test_normalize_sheet_overrides_ignores_unmapped_current_sheet_id():
    loaded = [{"current_sheet_id": "UNMAPPED_doc_4", "title": "Legend", "source_page_index": 3}]
    parsed = normalize_sheet_overrides_items(loaded)
    assert parsed == [
        {
            "sheet_id": "",
            "title": "Legend",
            "source_page_index": 3,
        }
    ]
