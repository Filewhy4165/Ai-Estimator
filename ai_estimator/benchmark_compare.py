from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare AI Estimator benchmark reports")
    parser.add_argument(
        "--baseline",
        default="",
        help="Path to baseline benchmark report JSON.",
    )
    parser.add_argument(
        "--candidate",
        default="",
        help="Path to candidate benchmark report JSON.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Compare the two most recent valid reports in --results-dir.",
    )
    parser.add_argument(
        "--results-dir",
        default="benchmarks/results",
        help="Directory used when --latest is set (default: benchmarks/results).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output file path for comparison JSON.",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with code 2 when overall trend is regressed.",
    )
    parser.add_argument(
        "--max-negative-delta",
        type=float,
        default=None,
        help=(
            "Optional threshold for allowed negative overall score delta. "
            "Exit with code 3 when delta is lower than negative threshold."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.latest:
        results_dir = Path(args.results_dir).expanduser().resolve()
        comparison = compare_latest_benchmark_reports(results_dir)
    else:
        baseline_text = str(args.baseline or "").strip()
        candidate_text = str(args.candidate or "").strip()
        if not baseline_text or not candidate_text:
            raise SystemExit("Provide --baseline and --candidate, or use --latest.")

        baseline_path = Path(baseline_text).expanduser().resolve()
        candidate_path = Path(candidate_text).expanduser().resolve()
        comparison = compare_reports_from_paths(baseline_path, candidate_path)

    output_json = json.dumps(comparison, indent=2)
    output_path_text = str(args.output or "").strip()
    if output_path_text:
        output_path = Path(output_path_text).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json, encoding="utf-8")
        print(f"Wrote comparison report to: {output_path}")

    print(output_json)

    if args.fail_on_regression and comparison.get("trend") == "regressed":
        raise SystemExit(2)

    max_negative_delta = args.max_negative_delta
    overall_delta = comparison.get("overall_score_delta")
    if (
        max_negative_delta is not None
        and isinstance(overall_delta, (int, float))
        and float(overall_delta) < -abs(float(max_negative_delta))
    ):
        raise SystemExit(3)


def compare_reports_from_paths(baseline_path: Path, candidate_path: Path) -> dict[str, object]:
    baseline_report = _load_json_dict_file(baseline_path)
    candidate_report = _load_json_dict_file(candidate_path)
    return compare_benchmark_reports(
        baseline_report=baseline_report,
        candidate_report=candidate_report,
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
    )


def compare_benchmark_reports(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    baseline_path: str,
    candidate_path: str,
) -> dict[str, object]:
    baseline_summary = _extract_report_summary(baseline_report)
    candidate_summary = _extract_report_summary(candidate_report)

    baseline_overall = _to_float_or_none(baseline_summary.get("overall_score"))
    candidate_overall = _to_float_or_none(candidate_summary.get("overall_score"))
    overall_delta = _score_delta(candidate_overall, baseline_overall)

    baseline_metrics = baseline_summary.get("metric_averages", {})
    candidate_metrics = candidate_summary.get("metric_averages", {})
    if not isinstance(baseline_metrics, dict):
        baseline_metrics = {}
    if not isinstance(candidate_metrics, dict):
        candidate_metrics = {}

    all_metrics = sorted(set(baseline_metrics.keys()).union(candidate_metrics.keys()))
    metric_deltas: dict[str, dict[str, object]] = {}
    for metric_name in all_metrics:
        baseline_metric = _to_float_or_none(baseline_metrics.get(metric_name))
        candidate_metric = _to_float_or_none(candidate_metrics.get(metric_name))
        metric_deltas[metric_name] = {
            "baseline": baseline_metric,
            "candidate": candidate_metric,
            "delta": _score_delta(candidate_metric, baseline_metric),
        }

    trend = "no_change"
    if overall_delta is not None:
        if overall_delta > 0:
            trend = "improved"
        elif overall_delta < 0:
            trend = "regressed"

    return {
        "baseline": {
            "path": baseline_path,
            "overall_score": baseline_overall,
            "case_count": baseline_summary.get("case_count"),
            "completed_count": baseline_summary.get("completed_count"),
            "failed_count": baseline_summary.get("failed_count"),
            "metric_averages": baseline_metrics,
        },
        "candidate": {
            "path": candidate_path,
            "overall_score": candidate_overall,
            "case_count": candidate_summary.get("case_count"),
            "completed_count": candidate_summary.get("completed_count"),
            "failed_count": candidate_summary.get("failed_count"),
            "metric_averages": candidate_metrics,
        },
        "overall_score_delta": overall_delta,
        "trend": trend,
        "metric_deltas": metric_deltas,
    }


def compare_latest_benchmark_reports(results_dir: Path) -> dict[str, object]:
    report_paths = list_recent_benchmark_report_paths(results_dir)
    if len(report_paths) < 2:
        raise RuntimeError(
            f"Need at least two benchmark reports in {results_dir} to compare latest trend."
        )

    candidate_path = report_paths[0]
    baseline_path = report_paths[1]
    comparison = compare_reports_from_paths(baseline_path, candidate_path)
    comparison["comparison_mode"] = "latest_pair"
    return comparison


def list_recent_benchmark_report_paths(results_dir: Path) -> list[Path]:
    if not results_dir.exists():
        return []

    candidates = sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    valid: list[Path] = []
    for path in candidates:
        try:
            parsed = _load_json_dict_file(path)
        except Exception:
            continue
        summary = _extract_report_summary(parsed)
        if "overall_score" in summary:
            valid.append(path)
    return valid


def build_benchmark_history(results_dir: Path, limit: int = 50, offset: int = 0) -> dict[str, object]:
    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))
    report_paths = list_recent_benchmark_report_paths(results_dir)

    items: list[dict[str, object]] = []
    for path in report_paths[safe_offset : safe_offset + safe_limit]:
        item = build_benchmark_history_item(path)
        if item is not None:
            items.append(item)

    return {
        "results_dir": str(results_dir),
        "total_available": len(report_paths),
        "total_returned": len(items),
        "limit": safe_limit,
        "offset": safe_offset,
        "items": items,
    }


def build_latest_benchmark_trend_summary(results_dir: Path) -> dict[str, object]:
    comparison = compare_latest_benchmark_reports(results_dir)
    history = build_benchmark_history(results_dir=results_dir, limit=2, offset=0)
    items = history.get("items", [])
    if not isinstance(items, list):
        items = []

    baseline = comparison.get("baseline", {})
    candidate = comparison.get("candidate", {})
    if not isinstance(baseline, dict):
        baseline = {}
    if not isinstance(candidate, dict):
        candidate = {}

    return {
        "results_dir": str(results_dir),
        "total_available": history.get("total_available", 0),
        "trend": comparison.get("trend"),
        "overall_score_delta": comparison.get("overall_score_delta"),
        "comparison_mode": comparison.get("comparison_mode", "latest_pair"),
        "baseline": {
            "path": baseline.get("path"),
            "overall_score": baseline.get("overall_score"),
            "generated_at_utc": items[1].get("generated_at_utc") if len(items) > 1 else None,
        },
        "candidate": {
            "path": candidate.get("path"),
            "overall_score": candidate.get("overall_score"),
            "generated_at_utc": items[0].get("generated_at_utc") if len(items) > 0 else None,
        },
        "metric_count": len(comparison.get("metric_deltas", {}))
        if isinstance(comparison.get("metric_deltas"), dict)
        else 0,
    }


def build_benchmark_score_timeline(results_dir: Path, limit: int = 30, offset: int = 0) -> dict[str, object]:
    history = build_benchmark_history(results_dir=results_dir, limit=limit, offset=offset)
    items = history.get("items", [])
    if not isinstance(items, list):
        items = []

    points: list[dict[str, object]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        score = _to_float_or_none(item.get("overall_score"))
        next_score: float | None = None
        if index + 1 < len(items):
            next_item = items[index + 1]
            if isinstance(next_item, dict):
                next_score = _to_float_or_none(next_item.get("overall_score"))
        delta_vs_previous = _score_delta(score, next_score)
        trend_vs_previous = "no_change"
        if delta_vs_previous is not None:
            if delta_vs_previous > 0:
                trend_vs_previous = "improved"
            elif delta_vs_previous < 0:
                trend_vs_previous = "regressed"

        points.append(
            {
                "index": index,
                "file_name": item.get("file_name"),
                "path": item.get("path"),
                "generated_at_utc": item.get("generated_at_utc"),
                "modified_local": item.get("modified_local"),
                "overall_score": score,
                "delta_vs_previous": delta_vs_previous,
                "trend_vs_previous": trend_vs_previous,
            }
        )

    return {
        "results_dir": history.get("results_dir"),
        "total_available": history.get("total_available", 0),
        "total_returned": len(points),
        "limit": history.get("limit", limit),
        "offset": history.get("offset", offset),
        "points": points,
    }


def evaluate_latest_benchmark_quality_gate(
    results_dir: Path,
    *,
    min_candidate_score: float | None = None,
    max_negative_delta: float | None = None,
    require_non_regression: bool = True,
    require_improvement: bool = False,
) -> dict[str, object]:
    summary = build_latest_benchmark_trend_summary(results_dir)
    candidate = summary.get("candidate", {})
    baseline = summary.get("baseline", {})
    if not isinstance(candidate, dict):
        candidate = {}
    if not isinstance(baseline, dict):
        baseline = {}

    candidate_score = _to_float_or_none(candidate.get("overall_score"))
    baseline_score = _to_float_or_none(baseline.get("overall_score"))
    overall_delta = _to_float_or_none(summary.get("overall_score_delta"))
    trend = str(summary.get("trend", "no_change"))

    failures: list[dict[str, object]] = []

    if min_candidate_score is not None:
        threshold = round(float(min_candidate_score), 4)
        if candidate_score is None:
            failures.append(
                {
                    "code": "missing_candidate_score",
                    "message": "Candidate overall score is missing; cannot evaluate minimum score threshold.",
                    "threshold": threshold,
                }
            )
        elif candidate_score < threshold:
            failures.append(
                {
                    "code": "candidate_score_below_threshold",
                    "message": "Candidate overall score is below the configured minimum.",
                    "threshold": threshold,
                    "actual": candidate_score,
                }
            )

    if max_negative_delta is not None:
        max_drop = round(abs(float(max_negative_delta)), 4)
        min_allowed_delta = round(-max_drop, 4)
        if overall_delta is None:
            failures.append(
                {
                    "code": "missing_overall_delta",
                    "message": "Overall delta is missing; cannot evaluate delta threshold.",
                    "threshold": min_allowed_delta,
                }
            )
        elif overall_delta < min_allowed_delta:
            failures.append(
                {
                    "code": "overall_delta_below_threshold",
                    "message": "Overall delta is below the configured negative-delta limit.",
                    "threshold": min_allowed_delta,
                    "actual": overall_delta,
                }
            )

    if require_improvement and trend != "improved":
        failures.append(
            {
                "code": "trend_not_improved",
                "message": "Quality gate requires an improved trend, but the latest trend is not improved.",
                "actual": trend,
            }
        )
    elif require_non_regression and trend == "regressed":
        failures.append(
            {
                "code": "trend_regressed",
                "message": "Quality gate requires non-regression, but the latest trend regressed.",
                "actual": trend,
            }
        )

    return {
        "results_dir": str(results_dir),
        "total_available": summary.get("total_available", 0),
        "passed": len(failures) == 0,
        "thresholds": {
            "min_candidate_score": min_candidate_score,
            "max_negative_delta": max_negative_delta,
            "require_non_regression": require_non_regression,
            "require_improvement": require_improvement,
        },
        "actual": {
            "trend": trend,
            "candidate_score": candidate_score,
            "baseline_score": baseline_score,
            "overall_score_delta": overall_delta,
        },
        "failures": failures,
    }


def build_benchmark_dashboard(
    results_dir: Path,
    *,
    history_limit: int = 20,
    history_offset: int = 0,
    timeline_limit: int = 30,
    timeline_offset: int = 0,
    gate_min_candidate_score: float | None = None,
    gate_max_negative_delta: float | None = None,
    gate_require_non_regression: bool = True,
    gate_require_improvement: bool = False,
) -> dict[str, object]:
    history = build_benchmark_history(results_dir=results_dir, limit=history_limit, offset=history_offset)
    timeline = build_benchmark_score_timeline(results_dir=results_dir, limit=timeline_limit, offset=timeline_offset)

    warnings: list[str] = []
    trend: dict[str, object] | None = None
    gate: dict[str, object] | None = None

    try:
        trend = build_latest_benchmark_trend_summary(results_dir)
    except RuntimeError as exc:
        warnings.append(str(exc))

    try:
        gate = evaluate_latest_benchmark_quality_gate(
            results_dir,
            min_candidate_score=gate_min_candidate_score,
            max_negative_delta=gate_max_negative_delta,
            require_non_regression=gate_require_non_regression,
            require_improvement=gate_require_improvement,
        )
    except RuntimeError as exc:
        warnings.append(str(exc))

    total_available = 0
    if isinstance(history.get("total_available"), int):
        total_available = int(history.get("total_available"))

    return {
        "results_dir": str(results_dir),
        "total_available": total_available,
        "history": history,
        "timeline": timeline,
        "trend": trend,
        "gate": gate,
        "warnings": warnings,
    }


def build_benchmark_history_item(path: Path) -> dict[str, object] | None:
    try:
        parsed = _load_json_dict_file(path)
    except Exception:
        return None

    summary = _extract_report_summary(parsed)
    if "overall_score" not in summary:
        return None

    stat = path.stat()
    modified_local = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return {
        "file_name": path.name,
        "path": str(path),
        "modified_local": modified_local,
        "generated_at_utc": parsed.get("generated_at_utc"),
        "overall_score": summary.get("overall_score"),
        "case_count": summary.get("case_count"),
        "completed_count": summary.get("completed_count"),
        "failed_count": summary.get("failed_count"),
    }


def _extract_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    if isinstance(summary, dict):
        return summary
    return {}


def _load_json_dict_file(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON file: {path}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return parsed


def _to_float_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    if isinstance(value, str):
        try:
            return round(float(value.strip()), 4)
        except ValueError:
            return None
    return None


def _score_delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(current - baseline, 4)


if __name__ == "__main__":
    main()
