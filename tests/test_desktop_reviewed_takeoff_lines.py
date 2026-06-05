from desktop.app import (
    filter_reviewed_takeoff_line_items,
    format_reviewed_takeoff_lines_payload,
    reviewed_takeoff_line_item_source,
    reviewed_takeoff_trade_filter_options,
    reviewed_takeoff_line_item_values,
)


def test_format_reviewed_takeoff_lines_payload_renders_estimator_rows() -> None:
    text = format_reviewed_takeoff_lines_payload(
        {
            "job_id": "job-1",
            "item_count": 1,
            "summary": {"total_by_unit": {"ft": 42.0}},
            "line_items": [
                {
                    "trade": "plumbing",
                    "quantity_name": "pipe",
                    "quantity": 42.0,
                    "unit": "ft",
                    "description": "2 inch copper pipe",
                    "cost_code": "22 11 16",
                    "sheet_id": "P101",
                    "source_page_index": 3,
                }
            ],
        }
    )

    assert "Reviewed Takeoff Lines" in text
    assert "Total: 42.0 ft" in text
    assert "plumbing - pipe: 42.0 ft" in text
    assert "description: 2 inch copper pipe" in text
    assert "cost code: 22 11 16" in text
    assert "source: P101 page 3" in text


def test_format_reviewed_takeoff_lines_payload_explains_empty_state() -> None:
    text = format_reviewed_takeoff_lines_payload(
        {"item_count": 0, "line_items": []},
        current_job_id="job-empty",
    )

    assert "Job: job-empty" in text
    assert "No reviewed takeoff line items found yet." in text
    assert "Measure Scale Visually" in text


def test_reviewed_takeoff_line_item_values_are_table_ready() -> None:
    values = reviewed_takeoff_line_item_values(
        {
            "trade": "mechanical",
            "quantity_name": "chilled water pipe",
            "quantity": 18.5,
            "unit": "ft",
            "description": "2 inch CHWS route",
            "cost_code": "23 21 13",
            "sheet_id": "M201",
            "source_page_index": 14,
        }
    )

    assert values == (
        "mechanical",
        "chilled water pipe",
        "18.5",
        "ft",
        "2 inch CHWS route",
        "23 21 13",
        "M201 page 14",
    )


def test_reviewed_takeoff_line_item_values_fill_missing_fields() -> None:
    values = reviewed_takeoff_line_item_values({})

    assert values == (
        "unknown work type",
        "line item",
        "-",
        "-",
        "-",
        "-",
        "sheet unknown",
    )


def test_reviewed_takeoff_line_item_source_parses_sheet_page_and_source_id() -> None:
    source = reviewed_takeoff_line_item_source(
        {
            "sheet_id": "M201",
            "source_page_index": "14",
            "source_id": "measurement-7",
        }
    )

    assert source == ("M201", 14, "measurement-7")


def test_reviewed_takeoff_line_item_source_ignores_invalid_page() -> None:
    source = reviewed_takeoff_line_item_source(
        {
            "sheet_id": "M201",
            "source_page_index": "page 14",
            "source_id": "",
        }
    )

    assert source == ("M201", None, "")


def test_reviewed_takeoff_trade_filter_options_are_sorted_and_include_all() -> None:
    options = reviewed_takeoff_trade_filter_options(
        [
            {"trade": "plumbing"},
            {"trade": "mechanical"},
            {"trade": ""},
            {"trade": "Electrical"},
            "not a row",
        ]
    )

    assert options == ["All work types", "Electrical", "mechanical", "plumbing"]


def test_filter_reviewed_takeoff_line_items_matches_trade_without_typing() -> None:
    items = [
        {"trade": "mechanical", "quantity_name": "pipe"},
        {"trade": "plumbing", "quantity_name": "fixture"},
        {"trade": "Mechanical", "quantity_name": "duct"},
        "bad row",
    ]

    filtered = filter_reviewed_takeoff_line_items(items, "mechanical")
    all_rows = filter_reviewed_takeoff_line_items(items, "All work types")

    assert [row["quantity_name"] for row in filtered] == ["pipe", "duct"]
    assert len(all_rows) == 3
