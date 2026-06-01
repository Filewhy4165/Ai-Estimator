from __future__ import annotations

from typing import Any


def build_spec_compliance_report(*, job_id: str, result: dict[str, Any] | None) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    spec_context = result.get("spec_context", {})
    spec_context = spec_context if isinstance(spec_context, dict) else {}

    applied_profiles = spec_context.get("applied_spec_profiles", [])
    if not isinstance(applied_profiles, list):
        applied_profiles = []
    missing = _as_string_list(spec_context.get("missing_from_drawings"))
    overlap = _as_string_list(spec_context.get("overlap_with_drawings"))
    required = _as_string_list(spec_context.get("required_trades_from_specs"))
    detected = _as_string_list(spec_context.get("detected_trades_from_drawings"))
    standards = _as_string_list(spec_context.get("detected_standard_refs"))

    if not spec_context or not applied_profiles:
        status = "no_specs_applied"
        recommendations = [
            "Attach agency/company specs in Project Setup if the takeoff must include specification-driven requirements."
        ]
    elif missing:
        status = "review_required"
        recommendations = [
            "Review spec-required trades that were not clearly detected on the drawings.",
            "Use drawings as the highest authority when drawing content conflicts with specifications.",
        ]
    else:
        status = "specs_aligned"
        recommendations = [
            "No missing spec-required trades were detected from the current spec context.",
            "Confirm product selections against detected standards before final procurement.",
        ]

    return {
        "job_id": job_id,
        "status": status,
        "authority_order": spec_context.get(
            "authority_order",
            ["drawings", "specifications", "assumptions"],
        ),
        "conflict_policy": spec_context.get(
            "conflict_policy",
            "If drawing content conflicts with specification language, drawings control.",
        ),
        "applied_spec_count": len(applied_profiles),
        "applied_spec_profiles": [_profile_summary(item) for item in applied_profiles],
        "detected_standard_refs": standards,
        "required_trades_from_specs": required,
        "detected_trades_from_drawings": detected,
        "overlap_with_drawings": overlap,
        "missing_from_drawings": missing,
        "recommendations": recommendations,
    }


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _profile_summary(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "spec_id": str(raw.get("spec_id", "")).strip(),
        "organization": str(raw.get("organization", "")).strip(),
        "agency": str(raw.get("agency", "")).strip(),
        "standard_name": str(raw.get("standard_name", "")).strip(),
        "project_type": str(raw.get("project_type", "")).strip(),
        "is_public": bool(raw.get("is_public", False)),
        "detected_standard_refs": _as_string_list(raw.get("detected_standard_refs")),
        "detected_trade_hints": _as_string_list(raw.get("detected_trade_hints")),
    }
