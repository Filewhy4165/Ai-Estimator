from desktop.app import format_reviewed_takeoff_lines_payload


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
