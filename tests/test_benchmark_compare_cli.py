import json
import os
import sys

from ai_estimator.benchmark_compare import compare_reports_from_paths, main


def _write_report(path, score: float) -> None:
    payload = {
        "summary": {
            "overall_score": score,
            "metric_averages": {"sheet_ids": score},
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compare_reports_from_paths(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    _write_report(baseline_path, 0.55)
    _write_report(candidate_path, 0.75)

    result = compare_reports_from_paths(baseline_path, candidate_path)

    assert result["trend"] == "improved"
    assert result["overall_score_delta"] == 0.2
    assert result["metric_deltas"]["sheet_ids"]["delta"] == 0.2


def test_cli_latest_writes_output_file(tmp_path, monkeypatch):
    older = tmp_path / "older.json"
    newer = tmp_path / "newer.json"
    _write_report(older, 0.6)
    _write_report(newer, 0.9)
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_010, 1_700_000_010))

    output_path = tmp_path / "comparison.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-estimator-benchmark-compare",
            "--latest",
            "--results-dir",
            str(tmp_path),
            "--output",
            str(output_path),
        ],
    )

    main()
    parsed = json.loads(output_path.read_text(encoding="utf-8"))
    assert parsed["comparison_mode"] == "latest_pair"
    assert parsed["trend"] == "improved"


def test_cli_latest_fail_on_regression_exits_two(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_report(baseline, 0.9)
    _write_report(candidate, 0.7)
    os.utime(baseline, (1_700_000_000, 1_700_000_000))
    os.utime(candidate, (1_700_000_010, 1_700_000_010))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-estimator-benchmark-compare",
            "--latest",
            "--results-dir",
            str(tmp_path),
            "--fail-on-regression",
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected SystemExit(2) when regression is detected")


def test_cli_latest_max_negative_delta_exits_three(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_report(baseline, 0.9)
    _write_report(candidate, 0.7)
    os.utime(baseline, (1_700_000_000, 1_700_000_000))
    os.utime(candidate, (1_700_000_010, 1_700_000_010))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-estimator-benchmark-compare",
            "--latest",
            "--results-dir",
            str(tmp_path),
            "--max-negative-delta",
            "0.1",
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 3
    else:
        raise AssertionError("Expected SystemExit(3) when negative delta exceeds threshold")
