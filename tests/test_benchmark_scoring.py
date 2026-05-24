from pathlib import Path

from ai_estimator.benchmark import (
    _collect_scale_map,
    _summarize_case_results,
    run_benchmark_manifest,
    score_case,
)


def test_collect_scale_map_prefers_detected_scale_with_best_confidence():
    payload = {
        "scale_analysis": {
            "by_sheet": [
                {"sheet_id": "A101", "detected_scale": None, "confidence": 0.95},
                {"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\"", "confidence": 0.75},
                {"sheet_id": "S201", "detected_scale": "1:100", "confidence": 0.6},
                {"sheet_id": "S201", "detected_scale": "1:50", "confidence": 0.8},
            ]
        }
    }

    result = _collect_scale_map(payload)
    assert result["A101"] == "1/8\" = 1'-0\""
    assert result["S201"] == "1:50"


def test_score_case_returns_metric_scores():
    payload = {
        "sheets_detected": [{"sheet_id": "A101"}, {"sheet_id": "S201"}],
        "scale_analysis": {
            "by_sheet": [
                {"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\"", "confidence": 0.75},
                {"sheet_id": "S201", "detected_scale": None, "confidence": 0.4},
            ]
        },
        "trade_scope": {"analyzed_trades": ["architectural", "structural"]},
        "quantity_takeoff": {"counts": {"door": 2, "window": 1}},
    }
    expected = {
        "sheet_ids": ["A101", "S201", "E101"],
        "scales_by_sheet": {"A101": "1/8\" = 1'-0\"", "S201": None},
        "analyzed_trades": ["architectural", "electrical"],
        "quantity_sanity": {
            "require_nonempty_counts": True,
            "min_total_count": 3,
            "min_counts_by_type": {"door": 2, "window": 2},
        },
    }

    result = score_case(payload, expected)
    metrics = result["metrics"]

    assert result["overall_score"] is not None
    assert result["evaluated_metric_count"] == 4

    assert metrics["sheet_ids"]["evaluated"] is True
    assert metrics["sheet_ids"]["missing_sheet_ids"] == ["E101"]
    assert metrics["sheet_ids"]["unexpected_sheet_ids"] == []

    assert metrics["scales"]["evaluated"] is True
    assert metrics["scales"]["score"] == 1.0

    assert metrics["trade_overlap"]["evaluated"] is True
    assert metrics["trade_overlap"]["score"] == 0.3333

    assert metrics["quantity_sanity"]["evaluated"] is True
    assert metrics["quantity_sanity"]["checks_total"] == 4
    assert metrics["quantity_sanity"]["checks_passed"] == 3


def test_score_case_skips_missing_expectations():
    payload = {
        "sheets_detected": [{"sheet_id": "A101"}],
        "scale_analysis": {"by_sheet": []},
        "trade_scope": {"analyzed_trades": ["architectural"]},
        "quantity_takeoff": {"counts": {}},
    }

    result = score_case(payload, expected={})
    metrics = result["metrics"]
    assert result["overall_score"] is None
    assert result["evaluated_metric_count"] == 0
    assert metrics["sheet_ids"]["evaluated"] is False
    assert metrics["scales"]["evaluated"] is False
    assert metrics["trade_overlap"]["evaluated"] is False
    assert metrics["quantity_sanity"]["evaluated"] is False


def test_summarize_case_results_aggregates_scores():
    case_results = [
        {
            "case_id": "c1",
            "status": "completed",
            "score": {
                "overall_score": 0.5,
                "metrics": {
                    "sheet_ids": {"evaluated": True, "score": 0.4},
                    "scales": {"evaluated": False},
                },
            },
        },
        {
            "case_id": "c2",
            "status": "completed",
            "score": {
                "overall_score": 0.9,
                "metrics": {
                    "sheet_ids": {"evaluated": True, "score": 0.8},
                    "scales": {"evaluated": True, "score": 1.0},
                },
            },
        },
        {"case_id": "c3", "status": "failed", "error": "boom"},
    ]

    summary = _summarize_case_results(case_results)
    assert summary["case_count"] == 3
    assert summary["completed_count"] == 2
    assert summary["failed_count"] == 1
    assert summary["overall_score"] == 0.7
    assert summary["metric_averages"]["sheet_ids"] == 0.6
    assert summary["metric_averages"]["scales"] == 1.0


def test_run_benchmark_manifest_marks_missing_pdf_as_failed(tmp_path: Path):
    manifest = {
        "cases": [
            {
                "case_id": "missing-pdf",
                "pdf_paths": [str(tmp_path / "not-found.pdf")],
                "expected": {"sheet_ids": ["A101"]},
            }
        ]
    }

    report = run_benchmark_manifest(
        manifest=manifest,
        manifest_path=tmp_path / "manifest.json",
        validate_schema=False,
    )
    case = report["cases"][0]
    assert case["status"] == "failed"
    assert "Missing PDF path(s)" in case["error"]
