import json
import os

from fastapi import HTTPException

from service.app import compare_benchmark_reports_endpoint, compare_latest_benchmark_reports_endpoint


def _write_report(path, score: float) -> None:
    payload = {
        "summary": {
            "overall_score": score,
            "metric_averages": {"sheet_ids": score},
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compare_benchmark_reports_endpoint(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    _write_report(baseline_path, 0.6)
    _write_report(candidate_path, 0.8)

    result = compare_benchmark_reports_endpoint(
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
    )

    assert result["trend"] == "improved"
    assert result["overall_score_delta"] == 0.2


def test_compare_benchmark_reports_endpoint_404_for_missing_baseline(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    _write_report(candidate_path, 0.8)

    try:
        compare_benchmark_reports_endpoint(
            baseline_path=str(tmp_path / "missing.json"),
            candidate_path=str(candidate_path),
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "Baseline report not found" in str(exc.detail)
    else:
        raise AssertionError("Expected HTTPException for missing baseline report")


def test_compare_latest_benchmark_reports_endpoint(tmp_path):
    older = tmp_path / "older.json"
    newer = tmp_path / "newer.json"
    _write_report(older, 0.4)
    _write_report(newer, 0.7)
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_010, 1_700_000_010))

    result = compare_latest_benchmark_reports_endpoint(results_dir=str(tmp_path))

    assert result["comparison_mode"] == "latest_pair"
    assert result["trend"] == "improved"
    assert result["overall_score_delta"] == 0.3


def test_compare_latest_benchmark_reports_endpoint_requires_two_reports(tmp_path):
    only = tmp_path / "only.json"
    _write_report(only, 0.5)
    os.utime(only, (1_700_000_000, 1_700_000_000))

    try:
        compare_latest_benchmark_reports_endpoint(results_dir=str(tmp_path))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Need at least two benchmark reports" in str(exc.detail)
    else:
        raise AssertionError("Expected HTTPException when fewer than two reports are present")
