import json
import os

from desktop.app import compare_benchmark_reports, compare_latest_benchmark_reports


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


def test_compare_latest_benchmark_reports_uses_newest_two(tmp_path):
    report_old = tmp_path / "old.json"
    report_mid = tmp_path / "mid.json"
    report_new = tmp_path / "new.json"

    report_old.write_text(json.dumps({"summary": {"overall_score": 0.2, "metric_averages": {}}}), encoding="utf-8")
    report_mid.write_text(json.dumps({"summary": {"overall_score": 0.6, "metric_averages": {}}}), encoding="utf-8")
    report_new.write_text(json.dumps({"summary": {"overall_score": 0.8, "metric_averages": {}}}), encoding="utf-8")

    # Ensure deterministic ordering by modification timestamp.
    os.utime(report_old, (1_700_000_000, 1_700_000_000))
    os.utime(report_mid, (1_700_000_010, 1_700_000_010))
    os.utime(report_new, (1_700_000_020, 1_700_000_020))

    result = compare_latest_benchmark_reports(tmp_path)
    assert result["comparison_mode"] == "latest_pair"
    assert result["baseline"]["path"].endswith("mid.json")
    assert result["candidate"]["path"].endswith("new.json")
    assert result["overall_score_delta"] == 0.2
    assert result["trend"] == "improved"


def test_compare_latest_benchmark_reports_requires_two_reports(tmp_path):
    only = tmp_path / "only.json"
    only.write_text(json.dumps({"summary": {"overall_score": 0.5}}), encoding="utf-8")
    os.utime(only, (1_700_000_000, 1_700_000_000))

    try:
        compare_latest_benchmark_reports(tmp_path)
    except RuntimeError as exc:
        assert "Need at least two benchmark reports" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when fewer than two reports are present")
