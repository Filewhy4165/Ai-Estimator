from desktop.app import compare_benchmark_reports


def test_compare_benchmark_reports_improved():
    baseline = {
        "summary": {
            "overall_score": 0.75,
            "case_count": 2,
            "completed_count": 2,
            "failed_count": 0,
            "metric_averages": {"sheet_ids": 0.5, "scales": 1.0},
        }
    }
    candidate = {
        "summary": {
            "overall_score": 0.9,
            "case_count": 2,
            "completed_count": 2,
            "failed_count": 0,
            "metric_averages": {"sheet_ids": 0.8, "scales": 1.0, "quantity_sanity": 0.9},
        }
    }
    result = compare_benchmark_reports(
        baseline_report=baseline,
        candidate_report=candidate,
        baseline_path="baseline.json",
        candidate_path="candidate.json",
    )

    assert result["trend"] == "improved"
    assert result["overall_score_delta"] == 0.15
    assert result["metric_deltas"]["sheet_ids"]["delta"] == 0.3
    assert result["metric_deltas"]["scales"]["delta"] == 0.0
    assert result["metric_deltas"]["quantity_sanity"]["baseline"] is None
    assert result["metric_deltas"]["quantity_sanity"]["candidate"] == 0.9


def test_compare_benchmark_reports_regressed_and_no_change():
    baseline = {"summary": {"overall_score": 1.0, "metric_averages": {"sheet_ids": 1.0}}}
    candidate = {"summary": {"overall_score": 0.8, "metric_averages": {"sheet_ids": 0.8}}}
    regressed = compare_benchmark_reports(
        baseline_report=baseline,
        candidate_report=candidate,
        baseline_path="a.json",
        candidate_path="b.json",
    )
    assert regressed["trend"] == "regressed"
    assert regressed["overall_score_delta"] == -0.2

    same = compare_benchmark_reports(
        baseline_report=baseline,
        candidate_report=baseline,
        baseline_path="a.json",
        candidate_path="a.json",
    )
    assert same["trend"] == "no_change"
    assert same["overall_score_delta"] == 0.0
