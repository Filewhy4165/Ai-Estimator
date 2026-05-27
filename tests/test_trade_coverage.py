from __future__ import annotations

from service.trade_coverage import build_trade_coverage_report


def test_trade_coverage_report_classifies_trade_statuses():
    payload = build_trade_coverage_report(
        job_id="job-1",
        result={
            "trade_scope": {
                "detected_trades": ["architectural", "electrical", "plumbing"],
                "analyzed_trades": ["architectural", "plumbing", "mechanical_hvac"],
            },
            "geometry": {
                "walls": [{"trade": "architectural"}],
                "doors": [{"trade": "architectural"}],
                "windows": [],
                "slabs": [],
                "roofs": [],
                "fixtures": [{"trade": "plumbing"}],
                "equipment": [],
                "annotations": {},
            },
            "quantity_takeoff": {
                "by_trade": {
                    "architectural": {"counts": {"door": 2}, "linear": {}, "area": {}, "volume": {}},
                    "plumbing": {"counts": {"fixture": 1}, "linear": {}, "area": {}, "volume": {}},
                    "mechanical_hvac": {"counts": {}, "linear": {}, "area": {}, "volume": {}},
                }
            },
        },
    )

    rows = {row["trade"]: row for row in payload["trades"]}
    assert rows["architectural"]["status"] == "covered"
    assert rows["plumbing"]["status"] == "covered"
    assert rows["electrical"]["status"] == "skipped"
    assert rows["mechanical_hvac"]["status"] == "forced_selected"
    assert payload["summary"]["status_counts"]["covered"] == 2
    assert payload["summary"]["needs_review_count"] == 1
    assert payload["needs_review_trades"] == ["electrical"]


def test_trade_coverage_report_handles_missing_result():
    payload = build_trade_coverage_report(job_id="job-2", result=None)
    assert payload["summary"]["total_trades"] == 0
    assert payload["trades"] == []
