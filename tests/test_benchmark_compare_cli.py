import json
import os
import sys

from ai_estimator.benchmark_compare import (
    build_benchmark_history,
    build_benchmark_score_timeline,
    build_latest_benchmark_trend_summary,
    compare_reports_from_paths,
    main,
)


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


def test_build_benchmark_history_paginates(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    third = tmp_path / "third.json"
    _write_report(first, 0.3)
    _write_report(second, 0.6)
    _write_report(third, 0.9)
    os.utime(first, (1_700_000_000, 1_700_000_000))
    os.utime(second, (1_700_000_010, 1_700_000_010))
    os.utime(third, (1_700_000_020, 1_700_000_020))

    payload = build_benchmark_history(results_dir=tmp_path, limit=2, offset=1)

    assert payload["total_available"] == 3
    assert payload["total_returned"] == 2
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    names = [item["file_name"] for item in payload["items"]]
    assert names == ["second.json", "first.json"]


def test_build_latest_benchmark_trend_summary(tmp_path):
    older = tmp_path / "older.json"
    newer = tmp_path / "newer.json"
    _write_report(older, 0.45)
    _write_report(newer, 0.7)
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_010, 1_700_000_010))

    payload = build_latest_benchmark_trend_summary(tmp_path)

    assert payload["comparison_mode"] == "latest_pair"
    assert payload["trend"] == "improved"
    assert payload["overall_score_delta"] == 0.25
    assert payload["total_available"] == 2
    assert payload["metric_count"] == 1


def test_build_latest_benchmark_trend_summary_requires_two_reports(tmp_path):
    only = tmp_path / "only.json"
    _write_report(only, 0.5)
    os.utime(only, (1_700_000_000, 1_700_000_000))

    try:
        build_latest_benchmark_trend_summary(tmp_path)
    except RuntimeError as exc:
        assert "Need at least two benchmark reports" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when fewer than two reports are present")


def test_build_benchmark_score_timeline(tmp_path):
    oldest = tmp_path / "oldest.json"
    middle = tmp_path / "middle.json"
    newest = tmp_path / "newest.json"
    _write_report(oldest, 0.3)
    _write_report(middle, 0.5)
    _write_report(newest, 0.8)
    os.utime(oldest, (1_700_000_000, 1_700_000_000))
    os.utime(middle, (1_700_000_010, 1_700_000_010))
    os.utime(newest, (1_700_000_020, 1_700_000_020))

    payload = build_benchmark_score_timeline(results_dir=tmp_path, limit=3, offset=0)
    points = payload["points"]

    assert payload["total_available"] == 3
    assert payload["total_returned"] == 3
    assert points[0]["file_name"] == "newest.json"
    assert points[0]["delta_vs_previous"] == 0.3
    assert points[0]["trend_vs_previous"] == "improved"
    assert points[1]["file_name"] == "middle.json"
    assert points[1]["delta_vs_previous"] == 0.2
    assert points[1]["trend_vs_previous"] == "improved"
    assert points[2]["file_name"] == "oldest.json"
    assert points[2]["delta_vs_previous"] is None
