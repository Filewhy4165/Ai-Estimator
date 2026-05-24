from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_estimator.pipeline import run_pipeline, sanitize_selected_trades


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Estimator benchmark runner")
    parser.add_argument("--manifest", required=True, help="Benchmark manifest JSON path.")
    parser.add_argument("--output", required=True, help="Output JSON report path.")
    parser.add_argument(
        "--schema-path",
        default="",
        help="Optional schema path passed through to pipeline validation.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Disable output schema validation during benchmark runs.",
    )
    parser.add_argument(
        "--fail-below",
        type=float,
        default=None,
        help="Optional threshold. Exit non-zero when overall score is below this value.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    manifest = _load_json_file(manifest_path)
    report = run_benchmark_manifest(
        manifest=manifest,
        manifest_path=manifest_path,
        validate_schema=not args.no_validate,
        schema_path=args.schema_path or None,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = report.get("summary", {})
    print(f"Wrote benchmark report to: {output_path}")
    print(f"Cases: {summary.get('case_count', 0)}")
    print(f"Completed: {summary.get('completed_count', 0)}")
    print(f"Failed: {summary.get('failed_count', 0)}")
    print(f"Overall score: {summary.get('overall_score')}")

    fail_below = args.fail_below
    overall_score = summary.get("overall_score")
    if fail_below is not None and isinstance(overall_score, (float, int)):
        if float(overall_score) < float(fail_below):
            raise SystemExit(2)


def run_benchmark_manifest(
    manifest: dict[str, Any],
    manifest_path: Path,
    validate_schema: bool = True,
    schema_path: str | None = None,
) -> dict[str, Any]:
    defaults = manifest.get("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}

    raw_cases = manifest.get("cases", [])
    if not isinstance(raw_cases, list):
        raise ValueError("Manifest field 'cases' must be a list.")

    case_results: list[dict[str, Any]] = []
    for index, raw_case in enumerate(raw_cases):
        case_result = _run_single_case(
            raw_case=raw_case,
            index=index,
            manifest_dir=manifest_path.parent,
            defaults=defaults,
            validate_schema=validate_schema,
            schema_path=schema_path,
        )
        case_results.append(case_result)

    summary = _summarize_case_results(case_results)
    return {
        "manifest_path": str(manifest_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "cases": case_results,
    }


def score_case(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    expected = expected if isinstance(expected, dict) else {}
    metrics: dict[str, dict[str, Any]] = {}

    metrics["sheet_ids"] = _score_sheet_ids(payload, expected)
    metrics["scales"] = _score_scales(payload, expected)
    metrics["trade_overlap"] = _score_trade_overlap(payload, expected)
    metrics["quantity_sanity"] = _score_quantity_sanity(payload, expected)

    scored_values = [
        float(metric["score"])
        for metric in metrics.values()
        if metric.get("evaluated") is True and isinstance(metric.get("score"), (float, int))
    ]
    overall_score: float | None = None
    if scored_values:
        overall_score = round(sum(scored_values) / len(scored_values), 4)

    return {
        "overall_score": overall_score,
        "evaluated_metric_count": len(scored_values),
        "metrics": metrics,
    }


def _run_single_case(
    raw_case: object,
    index: int,
    manifest_dir: Path,
    defaults: dict[str, Any],
    validate_schema: bool,
    schema_path: str | None,
) -> dict[str, Any]:
    start = time.perf_counter()
    case_id = f"case_{index + 1:03d}"
    if isinstance(raw_case, dict):
        case_id = str(raw_case.get("case_id") or case_id)
    else:
        return {
            "case_id": case_id,
            "status": "failed",
            "error": "Case entry is not an object.",
            "runtime_seconds": round(time.perf_counter() - start, 3),
        }

    try:
        pdf_paths = _resolve_pdf_paths(raw_case, defaults, manifest_dir)
        if not pdf_paths:
            raise ValueError("Case must include at least one PDF path.")
        missing_pdf_paths = [path for path in pdf_paths if not Path(path).exists()]
        if missing_pdf_paths:
            raise FileNotFoundError(
                "Missing PDF path(s): " + ", ".join(missing_pdf_paths[:10])
            )

        analysis_mode = str(raw_case.get("analysis_mode") or defaults.get("analysis_mode") or "auto")
        selected_trades = _resolve_selected_trades(raw_case, defaults)
        sheet_overrides = _resolve_sheet_overrides(raw_case, defaults, manifest_dir)
        notes = _resolve_notes(raw_case, defaults)

        payload = run_pipeline(
            pdf_paths=pdf_paths,
            analysis_mode=analysis_mode,
            selected_trades=selected_trades,
            sheet_overrides=sheet_overrides,
            notes=notes,
            validate_schema=validate_schema,
            schema_path=schema_path,
        )

        expected = raw_case.get("expected", {})
        score = score_case(payload, expected if isinstance(expected, dict) else {})
        issue_count = len(payload.get("issues_or_ambiguities", [])) if isinstance(payload, dict) else 0

        return {
            "case_id": case_id,
            "status": "completed",
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trades,
            "pdf_paths": pdf_paths,
            "issue_count": issue_count,
            "score": score,
            "runtime_seconds": round(time.perf_counter() - start, 3),
        }
    except Exception as exc:  # pragma: no cover - defensive failure capture
        return {
            "case_id": case_id,
            "status": "failed",
            "error": str(exc),
            "runtime_seconds": round(time.perf_counter() - start, 3),
        }


def _resolve_pdf_paths(
    case: dict[str, Any],
    defaults: dict[str, Any],
    manifest_dir: Path,
) -> list[str]:
    raw = case.get("pdf_paths", defaults.get("pdf_paths", []))
    paths: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                continue
            resolved = _resolve_path(item.strip(), manifest_dir)
            paths.append(str(resolved))
    elif isinstance(raw, str) and raw.strip():
        resolved = _resolve_path(raw.strip(), manifest_dir)
        paths.append(str(resolved))
    return paths


def _resolve_selected_trades(case: dict[str, Any], defaults: dict[str, Any]) -> list[str]:
    if "selected_trades" in case:
        raw = case.get("selected_trades")
    else:
        raw = defaults.get("selected_trades", [])

    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return sanitize_selected_trades(raw)
    return []


def _resolve_sheet_overrides(
    case: dict[str, Any],
    defaults: dict[str, Any],
    manifest_dir: Path,
) -> list[dict[str, Any]] | None:
    if "sheet_overrides" in case:
        raw = case.get("sheet_overrides")
    elif "sheet_overrides" in defaults:
        raw = defaults.get("sheet_overrides")
    else:
        raw = None

    if isinstance(raw, list):
        return _normalize_sheet_overrides(raw)
    if isinstance(raw, str) and raw.strip():
        overrides_path = _resolve_path(raw.strip(), manifest_dir)
        loaded = _load_json_file(overrides_path)
        if isinstance(loaded, list):
            return _normalize_sheet_overrides(loaded)
    return None


def _resolve_notes(case: dict[str, Any], defaults: dict[str, Any]) -> str | None:
    raw = case.get("notes", defaults.get("notes", None))
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _normalize_sheet_overrides(raw: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {
            "sheet_id": str(item.get("sheet_id", "")).strip(),
            "title": str(item.get("title", "")).strip(),
        }
        page_index = item.get("source_page_index")
        parsed_page_index: int | None = None
        if isinstance(page_index, int) and page_index >= 1:
            parsed_page_index = page_index
        elif isinstance(page_index, str) and page_index.strip().isdigit():
            parsed = int(page_index.strip())
            if parsed >= 1:
                parsed_page_index = parsed
        if parsed_page_index is not None:
            row["source_page_index"] = parsed_page_index
        normalized.append(row)
    return normalized


def _score_sheet_ids(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    raw_expected = expected.get("sheet_ids")
    if not isinstance(raw_expected, list):
        return {"evaluated": False, "reason": "No expected.sheet_ids provided."}

    expected_set = {str(item).strip() for item in raw_expected if str(item).strip()}
    predicted_set = {
        str(item.get("sheet_id", "")).strip()
        for item in _safe_list(payload.get("sheets_detected"))
        if isinstance(item, dict) and str(item.get("sheet_id", "")).strip()
    }

    true_positive = expected_set.intersection(predicted_set)
    precision = _ratio(len(true_positive), len(predicted_set))
    recall = _ratio(len(true_positive), len(expected_set))
    f1 = _f1_score(precision, recall)

    return {
        "evaluated": True,
        "score": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "expected_count": len(expected_set),
        "predicted_count": len(predicted_set),
        "matched_count": len(true_positive),
        "missing_sheet_ids": sorted(expected_set.difference(predicted_set)),
        "unexpected_sheet_ids": sorted(predicted_set.difference(expected_set)),
        "exact_set_match": expected_set == predicted_set,
    }


def _score_scales(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    raw_expected = expected.get("scales_by_sheet")
    if not isinstance(raw_expected, dict) or not raw_expected:
        return {"evaluated": False, "reason": "No expected.scales_by_sheet provided."}

    expected_map = {str(k).strip(): _normalize_scale(v) for k, v in raw_expected.items() if str(k).strip()}
    predicted_map = _collect_scale_map(payload)

    hits = 0
    mismatches: list[dict[str, Any]] = []
    for sheet_id, expected_scale in expected_map.items():
        predicted_scale = predicted_map.get(sheet_id)
        if predicted_scale == expected_scale:
            hits += 1
        else:
            mismatches.append(
                {
                    "sheet_id": sheet_id,
                    "expected_scale": expected_scale,
                    "predicted_scale": predicted_scale,
                }
            )

    total = len(expected_map)
    score = _ratio(hits, total)
    return {
        "evaluated": True,
        "score": round(score, 4),
        "hits": hits,
        "total": total,
        "mismatches": mismatches,
    }


def _score_trade_overlap(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    raw_expected = expected.get("analyzed_trades")
    if not isinstance(raw_expected, list):
        return {"evaluated": False, "reason": "No expected.analyzed_trades provided."}

    expected_set = {str(item).strip() for item in raw_expected if str(item).strip()}
    trade_scope = payload.get("trade_scope", {})
    if not isinstance(trade_scope, dict):
        trade_scope = {}
    raw_predicted = trade_scope.get("analyzed_trades", [])
    predicted_set = (
        {str(item).strip() for item in raw_predicted if str(item).strip()}
        if isinstance(raw_predicted, list)
        else set()
    )

    union = expected_set.union(predicted_set)
    intersection = expected_set.intersection(predicted_set)
    score = 1.0 if not union else len(intersection) / len(union)

    return {
        "evaluated": True,
        "score": round(score, 4),
        "expected_trades": sorted(expected_set),
        "predicted_trades": sorted(predicted_set),
        "missing_trades": sorted(expected_set.difference(predicted_set)),
        "unexpected_trades": sorted(predicted_set.difference(expected_set)),
    }


def _score_quantity_sanity(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    raw_rules = expected.get("quantity_sanity")
    if not isinstance(raw_rules, dict):
        return {"evaluated": False, "reason": "No expected.quantity_sanity provided."}

    takeoff = payload.get("quantity_takeoff", {})
    if not isinstance(takeoff, dict):
        takeoff = {}
    counts = takeoff.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}

    checks_total = 0
    checks_passed = 0
    details: list[dict[str, Any]] = []

    require_nonempty_counts = raw_rules.get("require_nonempty_counts")
    if isinstance(require_nonempty_counts, bool):
        checks_total += 1
        count_total = sum(_to_int(value) for value in counts.values())
        passed = count_total > 0 if require_nonempty_counts else True
        checks_passed += 1 if passed else 0
        details.append(
            {
                "check": "require_nonempty_counts",
                "passed": passed,
                "expected": require_nonempty_counts,
                "actual_total_counts": count_total,
            }
        )

    min_total_count = raw_rules.get("min_total_count")
    if isinstance(min_total_count, int):
        checks_total += 1
        count_total = sum(_to_int(value) for value in counts.values())
        passed = count_total >= min_total_count
        checks_passed += 1 if passed else 0
        details.append(
            {
                "check": "min_total_count",
                "passed": passed,
                "expected_min_total_count": min_total_count,
                "actual_total_counts": count_total,
            }
        )

    min_counts_by_type = raw_rules.get("min_counts_by_type")
    if isinstance(min_counts_by_type, dict):
        for element_type, min_count in min_counts_by_type.items():
            if not isinstance(min_count, int):
                continue
            checks_total += 1
            actual = _to_int(counts.get(str(element_type), 0))
            passed = actual >= min_count
            checks_passed += 1 if passed else 0
            details.append(
                {
                    "check": "min_counts_by_type",
                    "element_type": str(element_type),
                    "passed": passed,
                    "expected_min_count": min_count,
                    "actual_count": actual,
                }
            )

    if checks_total == 0:
        return {
            "evaluated": False,
            "reason": "quantity_sanity provided but no valid checks were configured.",
        }

    score = _ratio(checks_passed, checks_total)
    return {
        "evaluated": True,
        "score": round(score, 4),
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "details": details,
    }


def _collect_scale_map(payload: dict[str, Any]) -> dict[str, str | None]:
    scale_analysis = payload.get("scale_analysis", {})
    if not isinstance(scale_analysis, dict):
        return {}
    by_sheet = scale_analysis.get("by_sheet", [])
    if not isinstance(by_sheet, list):
        return {}

    picked: dict[str, dict[str, Any]] = {}
    for row in by_sheet:
        if not isinstance(row, dict):
            continue
        sheet_id = str(row.get("sheet_id", "")).strip()
        if not sheet_id:
            continue
        detected = _normalize_scale(row.get("detected_scale"))
        confidence = _to_float(row.get("confidence"), default=0.0)
        candidate = {"scale": detected, "confidence": confidence}
        current = picked.get(sheet_id)
        if current is None:
            picked[sheet_id] = candidate
            continue

        current_scale = current.get("scale")
        current_conf = _to_float(current.get("confidence"), default=0.0)
        if current_scale is None and detected is not None:
            picked[sheet_id] = candidate
            continue
        if current_scale is not None and detected is None:
            continue
        if confidence > current_conf:
            picked[sheet_id] = candidate

    return {sheet_id: data.get("scale") for sheet_id, data in picked.items()}


def _summarize_case_results(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in case_results if row.get("status") == "completed"]
    failed = [row for row in case_results if row.get("status") == "failed"]

    overall_scores = []
    for row in completed:
        score = row.get("score", {})
        if not isinstance(score, dict):
            continue
        case_overall = score.get("overall_score")
        if isinstance(case_overall, (float, int)):
            overall_scores.append(float(case_overall))

    aggregate_overall: float | None = None
    if overall_scores:
        aggregate_overall = round(sum(overall_scores) / len(overall_scores), 4)

    metric_sums: dict[str, float] = {}
    metric_counts: dict[str, int] = {}
    for row in completed:
        score = row.get("score", {})
        if not isinstance(score, dict):
            continue
        metrics = score.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        for metric_name, metric_value in metrics.items():
            if not isinstance(metric_value, dict):
                continue
            if metric_value.get("evaluated") is not True:
                continue
            metric_score = metric_value.get("score")
            if not isinstance(metric_score, (float, int)):
                continue
            metric_sums[metric_name] = metric_sums.get(metric_name, 0.0) + float(metric_score)
            metric_counts[metric_name] = metric_counts.get(metric_name, 0) + 1

    metric_averages: dict[str, float] = {}
    for metric_name, value_sum in metric_sums.items():
        count = metric_counts.get(metric_name, 0)
        if count > 0:
            metric_averages[metric_name] = round(value_sum / count, 4)

    return {
        "case_count": len(case_results),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "overall_score": aggregate_overall,
        "metric_averages": metric_averages,
    }


def _normalize_scale(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = " ".join(text.upper().split())
    normalized = (
        normalized.replace("”", "\"")
        .replace("“", "\"")
        .replace("′", "'")
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    return normalized


def _load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_path(path_text: str, base_dir: Path) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = base_dir.joinpath(path)
    return path.resolve()


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0 if numerator <= 0 else 0.0
    return numerator / denominator


def _f1_score(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _to_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return default


if __name__ == "__main__":
    main()
