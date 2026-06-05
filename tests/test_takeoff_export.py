from service.takeoff_export import build_takeoff_csv, build_takeoff_rows


def _result():
    return {
        "quantity_takeoff": {
            "linear": {
                "explicit_dimensions_total_ft": 25.0,
                "vector_linework_by_sheet_ft": {"A101": 120.5},
            },
            "area": {},
            "volume": {},
            "counts": {"door": 2},
            "line_items": [
                {
                    "source": "manual_visual_measurement",
                    "sheet_id": "P101",
                    "source_page_index": 3,
                    "trade": "plumbing",
                    "quantity_bucket": "linear",
                    "quantity_name": "pipe",
                    "description": "2 inch copper pipe",
                    "cost_code": "22 11 16",
                    "quantity": 42.0,
                    "unit": "ft",
                }
            ],
            "by_trade": {
                "architectural": {
                    "linear": {"explicit_dimensions_total_ft": 25.0},
                    "area": {},
                    "volume": {},
                    "counts": {"door": 2},
                }
            },
        },
        "cost_mapping": {
            "cost_codes": {
                "csi_masterformat": {
                    "architectural": ["08", "09"],
                }
            }
        },
    }


def test_build_takeoff_rows_flattens_overall_trade_and_cost_codes():
    rows = build_takeoff_rows(job_id="job-1", result=_result())

    assert {
        "job_id": "job-1",
        "scope": "overall",
        "trade": "",
        "quantity_bucket": "linear",
        "quantity_name": "explicit_dimensions_total_ft",
        "value": "25.0",
        "unit_hint": "ft",
        "source": "quantity_takeoff",
    } in rows
    assert any(row["quantity_name"] == "vector_linework_by_sheet_ft.A101" for row in rows)
    assert any(row["scope"] == "trade" and row["trade"] == "architectural" for row in rows)
    assert {
        "job_id": "job-1",
        "scope": "line_item",
        "trade": "plumbing",
        "quantity_bucket": "linear",
        "quantity_name": "pipe | 2 inch copper pipe | cost 22 11 16 | sheet P101 p3",
        "value": "42.0",
        "unit_hint": "ft",
        "source": "manual_visual_measurement",
    } in rows
    assert any(row["quantity_bucket"] == "cost_codes" and row["value"] == "08; 09" for row in rows)


def test_build_takeoff_csv_includes_header_and_rows():
    csv_text = build_takeoff_csv(job_id="job-1", result=_result())

    assert csv_text.startswith("job_id,scope,trade,quantity_bucket,quantity_name,value,unit_hint,source\n")
    assert "job-1,overall,,counts,door,2,count,quantity_takeoff\n" in csv_text
