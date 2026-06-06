from desktop.app import (
    DesktopEstimatorApp,
    filter_reviewed_takeoff_line_items,
    format_reviewed_takeoff_line_item_totals,
    format_reviewed_takeoff_lines_payload,
    reviewed_takeoff_line_item_csv_row,
    reviewed_takeoff_line_item_csv_rows,
    reviewed_takeoff_line_item_rollup_values,
    reviewed_takeoff_line_item_rollup_filter_values,
    reviewed_takeoff_line_item_rollup_match_values,
    reviewed_takeoff_line_item_rollups,
    reviewed_takeoff_line_item_rollup_csv_row,
    reviewed_takeoff_line_item_rollup_csv_rows,
    reviewed_takeoff_line_item_matches_rollup,
    reviewed_takeoff_line_item_source,
    reviewed_takeoff_line_item_totals_by_unit,
    reviewed_takeoff_item_filter_options,
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


def test_reviewed_takeoff_item_filter_options_follow_selected_trade() -> None:
    items = [
        {"trade": "mechanical", "quantity_name": "pipe"},
        {"trade": "mechanical", "quantity_name": "duct"},
        {"trade": "plumbing", "quantity_name": "pipe"},
        {"trade": "mechanical", "quantity_name": ""},
    ]

    assert reviewed_takeoff_item_filter_options(items, "mechanical") == [
        "All measured items",
        "duct",
        "pipe",
    ]
    assert reviewed_takeoff_item_filter_options(items, "plumbing") == [
        "All measured items",
        "pipe",
    ]


def test_filter_reviewed_takeoff_line_items_matches_trade_and_item() -> None:
    items = [
        {"trade": "mechanical", "quantity_name": "pipe", "quantity": 10},
        {"trade": "mechanical", "quantity_name": "duct", "quantity": 20},
        {"trade": "plumbing", "quantity_name": "pipe", "quantity": 30},
    ]

    filtered = filter_reviewed_takeoff_line_items(items, "mechanical", "pipe")

    assert filtered == [{"trade": "mechanical", "quantity_name": "pipe", "quantity": 10}]


def test_reviewed_takeoff_line_item_totals_sum_numeric_quantities_by_unit() -> None:
    totals = reviewed_takeoff_line_item_totals_by_unit(
        [
            {"quantity": 10, "unit": "ft"},
            {"quantity": "2.5", "unit": "ft"},
            {"quantity": 3, "unit": "ea"},
            {"quantity": "not numeric", "unit": "ft"},
            "bad row",
        ]
    )

    assert totals == {"ft": 12.5, "ea": 3.0}
    assert format_reviewed_takeoff_line_item_totals(totals) == "3 ea, 12.5 ft"


def test_format_reviewed_takeoff_line_item_totals_handles_empty_totals() -> None:
    assert format_reviewed_takeoff_line_item_totals({}) == "none"


def test_reviewed_takeoff_line_item_csv_row_normalizes_export_fields() -> None:
    row = reviewed_takeoff_line_item_csv_row(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "quantity": 12.5,
            "unit": "ft",
            "description": "CHWS route",
            "assembly": "Hydronic pipe",
            "cost_code": "23 21 13",
            "sheet_id": "M201",
            "source_page_index": 14,
            "source_id": "m-1",
            "label": "M1",
        }
    )

    assert row == {
        "trade": "mechanical",
        "quantity_name": "pipe",
        "quantity": "12.5",
        "unit": "ft",
        "description": "CHWS route",
        "assembly": "Hydronic pipe",
        "cost_code": "23 21 13",
        "sheet_id": "M201",
        "source_page_index": "14",
        "source_id": "m-1",
        "label": "M1",
    }


def test_reviewed_takeoff_line_item_csv_rows_skip_invalid_rows() -> None:
    rows = reviewed_takeoff_line_item_csv_rows(
        [
            {"trade": "mechanical", "quantity_name": "pipe"},
            "bad row",
        ]
    )

    assert len(rows) == 1
    assert rows[0]["trade"] == "mechanical"
    assert rows[0]["quantity_name"] == "pipe"


def test_reviewed_takeoff_line_item_rollups_group_by_trade_item_unit_and_cost_code() -> None:
    rollups = reviewed_takeoff_line_item_rollups(
        [
            {
                "trade": "mechanical",
                "quantity_name": "pipe",
                "quantity": 10,
                "unit": "ft",
                "cost_code": "23 21 13",
                "sheet_id": "M201",
            },
            {
                "trade": "mechanical",
                "quantity_name": "pipe",
                "quantity": "2.5",
                "unit": "ft",
                "cost_code": "23 21 13",
                "sheet_id": "M202",
            },
            {
                "trade": "mechanical",
                "quantity_name": "duct",
                "quantity": 3,
                "unit": "ea",
                "cost_code": "23 31 13",
                "sheet_id": "M201",
            },
            "bad row",
        ]
    )

    assert rollups == [
        {
            "trade": "mechanical",
            "quantity_name": "duct",
            "unit": "ea",
            "cost_code": "23 31 13",
            "quantity": 3.0,
            "line_count": 1,
            "source_sheets": "M201",
        },
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "unit": "ft",
            "cost_code": "23 21 13",
            "quantity": 12.5,
            "line_count": 2,
            "source_sheets": "M201, M202",
        },
    ]


def test_reviewed_takeoff_line_item_rollup_values_are_table_ready() -> None:
    values = reviewed_takeoff_line_item_rollup_values(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "quantity": 12.5,
            "unit": "ft",
            "line_count": 2,
            "cost_code": "23 21 13",
            "source_sheets": "M201, M202",
        }
    )

    assert values == ("mechanical", "pipe", "12.5", "ft", "2", "23 21 13", "M201, M202")


def test_reviewed_takeoff_line_item_rollup_filter_values_match_detail_filters() -> None:
    filters = reviewed_takeoff_line_item_rollup_filter_values(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "quantity": 12.5,
            "unit": "ft",
        }
    )

    assert filters == ("mechanical", "pipe")


def test_reviewed_takeoff_line_item_rollup_filter_values_fill_missing_fields() -> None:
    assert reviewed_takeoff_line_item_rollup_filter_values({}) == (
        "unknown work type",
        "line item",
    )


def test_reviewed_takeoff_line_item_rollup_match_values_include_unit_and_cost_code() -> None:
    values = reviewed_takeoff_line_item_rollup_match_values(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "unit": "ft",
            "cost_code": "23 21 13",
        }
    )

    assert values == ("mechanical", "pipe", "ft", "23 21 13")


def test_reviewed_takeoff_line_item_matches_rollup_requires_exact_grouping() -> None:
    row = {
        "trade": "mechanical",
        "quantity_name": "pipe",
        "unit": "ft",
        "cost_code": "23 21 13",
    }

    assert reviewed_takeoff_line_item_matches_rollup(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "unit": "ft",
            "cost_code": "23 21 13",
        },
        row,
    )
    assert not reviewed_takeoff_line_item_matches_rollup(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "unit": "lf",
            "cost_code": "23 21 13",
        },
        row,
    )
    assert not reviewed_takeoff_line_item_matches_rollup(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "unit": "ft",
            "cost_code": "22 11 16",
        },
        row,
    )
    assert not reviewed_takeoff_line_item_matches_rollup("bad row", row)


def test_reviewed_takeoff_line_item_rollup_csv_row_matches_export_fields() -> None:
    row = reviewed_takeoff_line_item_rollup_csv_row(
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "quantity": 12.5,
            "unit": "ft",
            "line_count": 2,
            "cost_code": "23 21 13",
            "source_sheets": "M201, M202",
        }
    )

    assert row == {
        "trade": "mechanical",
        "quantity_name": "pipe",
        "quantity": "12.5",
        "unit": "ft",
        "line_count": "2",
        "cost_code": "23 21 13",
        "source_sheets": "M201, M202",
    }


def test_reviewed_takeoff_line_item_rollup_csv_rows_group_source_items() -> None:
    rows = reviewed_takeoff_line_item_rollup_csv_rows(
        [
            {
                "trade": "mechanical",
                "quantity_name": "pipe",
                "quantity": 10,
                "unit": "ft",
                "cost_code": "23 21 13",
                "sheet_id": "M201",
            },
            {
                "trade": "mechanical",
                "quantity_name": "pipe",
                "quantity": 2,
                "unit": "ft",
                "cost_code": "23 21 13",
                "sheet_id": "M202",
            },
        ]
    )

    assert rows == [
        {
            "trade": "mechanical",
            "quantity_name": "pipe",
            "quantity": "12",
            "unit": "ft",
            "line_count": "2",
            "cost_code": "23 21 13",
            "source_sheets": "M201, M202",
        }
    ]


def test_reviewed_takeoff_controls_have_beginner_help_specs() -> None:
    app = object.__new__(DesktopEstimatorApp)
    specs = app._control_specs_for_ui()

    for key in [
        "show_reviewed_takeoff_lines",
        "open_selected_line_source",
        "save_filtered_reviewed_csv",
        "save_rollup_csv",
        "show_selected_rollup_detail",
    ]:
        spec = specs[key]
        assert spec["pro_label"]
        assert spec["beginner_label"]
        assert spec["pro_tip"]
        assert spec["beginner_tip"]
