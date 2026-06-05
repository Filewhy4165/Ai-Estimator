from service.takeoff_line_items import build_takeoff_line_items_payload


def test_build_takeoff_line_items_payload_filters_and_summarizes():
    result = {
        "quantity_takeoff": {
            "line_items": [
                {
                    "source": "manual_visual_measurement",
                    "source_id": "m1",
                    "sheet_id": "P101",
                    "source_page_index": 3,
                    "trade": "plumbing",
                    "quantity_bucket": "linear",
                    "quantity_name": "pipe",
                    "description": "Copper pipe",
                    "cost_code": "22 11 16",
                    "quantity": 42.0,
                    "unit": "ft",
                    "known_length_ft": 42.0,
                    "measured_pdf_units": 210.0,
                },
                {
                    "source": "manual_visual_measurement",
                    "source_id": "m2",
                    "sheet_id": "E101",
                    "source_page_index": 4,
                    "trade": "electrical",
                    "quantity_bucket": "linear",
                    "quantity_name": "conduit",
                    "description": "EMT conduit",
                    "cost_code": "26 05 33",
                    "quantity": 18.5,
                    "unit": "ft",
                },
            ]
        }
    }

    payload = build_takeoff_line_items_payload(job_id="job-1", result=result)

    assert payload["item_count"] == 2
    assert payload["summary"]["total_by_unit"] == {"ft": 60.5}
    assert payload["summary"]["count_by_trade"] == {"electrical": 1, "plumbing": 1}
    assert payload["summary"]["total_by_trade_unit"]["plumbing"] == {"ft": 42.0}
    assert payload["summary"]["total_by_name_unit"]["pipe"] == {"ft": 42.0}

    filtered = build_takeoff_line_items_payload(
        job_id="job-1",
        result=result,
        trade="plumbing",
        quantity_name="pipe",
    )

    assert filtered["item_count"] == 1
    assert filtered["line_items"][0]["trade"] == "plumbing"
    assert filtered["line_items"][0]["quantity_name"] == "pipe"
