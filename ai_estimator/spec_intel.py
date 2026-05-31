from __future__ import annotations

import re
from typing import Any

from ai_estimator.constants import TRADE_NAMES


_STANDARD_PATTERNS = [
    re.compile(r"\bASTM\s+[A-Z]?\d+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bACI\s+\d+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bAISC\s+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bASME\s+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bANSI\s+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bASHRAE\s+\d+(?:\.\d+)?[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bNFPA\s+\d+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bUL\s+\d+[A-Z0-9\-]*\b", re.IGNORECASE),
    re.compile(r"\bSMACNA\b", re.IGNORECASE),
    re.compile(r"\bNEC\b", re.IGNORECASE),
    re.compile(r"\bIBC\s+\d{4}\b", re.IGNORECASE),
    re.compile(r"\bIMC\s+\d{4}\b", re.IGNORECASE),
    re.compile(r"\bIPC\s+\d{4}\b", re.IGNORECASE),
]


_TRADE_HINTS: list[tuple[str, str]] = [
    ("architectural", "architectural"),
    ("structure", "structural"),
    ("structural", "structural"),
    ("civil", "civil_site"),
    ("site", "civil_site"),
    ("landscape", "landscape"),
    ("finish", "interiors_finishes"),
    ("interior", "interiors_finishes"),
    ("fire sprinkler", "fire_protection"),
    ("fire protection", "fire_protection"),
    ("plumb", "plumbing"),
    ("hvac", "mechanical_hvac"),
    ("mechanical", "mechanical_hvac"),
    ("duct", "mechanical_hvac"),
    ("electrical", "electrical"),
    ("lighting", "electrical"),
    ("low voltage", "low_voltage_communications_it"),
    ("communication", "low_voltage_communications_it"),
    ("data cabling", "low_voltage_communications_it"),
    ("security", "security_access_alarm"),
    ("access control", "security_access_alarm"),
    ("alarm", "security_access_alarm"),
    ("elevator", "conveying"),
    ("conveyor", "conveying"),
    ("equipment", "equipment_specialties"),
    ("specialty", "equipment_specialties"),
]


def parse_csv_tokens(raw: str | None) -> list[str]:
    if raw is None:
        return []
    seen: set[str] = set()
    items: list[str] = []
    for token in raw.split(","):
        clean = token.strip()
        if not clean:
            continue
        lowered = clean.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(clean)
    return items


def extract_standard_references(text: str, *, limit: int = 120) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    if not text:
        return refs
    for pattern in _STANDARD_PATTERNS:
        for match in pattern.findall(text):
            clean = " ".join(str(match).split()).upper()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            refs.append(clean)
            if len(refs) >= limit:
                return refs
    refs.sort()
    return refs


def extract_trade_hints(text: str) -> list[str]:
    found: set[str] = set()
    lowered = text.lower()
    for marker, trade in _TRADE_HINTS:
        if marker in lowered and trade in TRADE_NAMES:
            found.add(trade)
    return sorted(found)


def build_spec_context(
    *,
    spec_profiles: list[dict[str, Any]] | None,
    detected_trades: list[str] | None,
) -> dict[str, Any]:
    profiles = spec_profiles or []
    detected = sorted({trade for trade in (detected_trades or []) if trade in TRADE_NAMES})

    applied_profiles: list[dict[str, Any]] = []
    required_trades: set[str] = set()
    references: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        refs = profile.get("detected_standard_refs", [])
        trades = profile.get("detected_trade_hints", [])
        clean_refs = sorted(
            {
                " ".join(str(item).split()).upper()
                for item in refs
                if " ".join(str(item).split())
            }
        )
        clean_trades = sorted(
            {str(item).strip() for item in trades if str(item).strip() in TRADE_NAMES}
        )
        references.update(clean_refs)
        required_trades.update(clean_trades)
        applied_profiles.append(
            {
                "spec_id": str(profile.get("spec_id", "")).strip(),
                "organization": str(profile.get("organization", "")).strip(),
                "agency": str(profile.get("agency", "")).strip(),
                "standard_name": str(profile.get("standard_name", "")).strip(),
                "project_type": str(profile.get("project_type", "")).strip(),
                "detected_standard_refs": clean_refs,
                "detected_trade_hints": clean_trades,
                "is_public": bool(profile.get("is_public", False)),
            }
        )

    required = sorted(required_trades)
    missing_from_drawings = [trade for trade in required if trade not in detected]
    overlap_with_drawings = [trade for trade in required if trade in detected]

    return {
        "authority_order": ["drawings", "specifications", "assumptions"],
        "conflict_policy": "If drawing content conflicts with specification language, drawings control.",
        "applied_spec_count": len(applied_profiles),
        "applied_spec_profiles": applied_profiles,
        "detected_standard_refs": sorted(references),
        "required_trades_from_specs": required,
        "detected_trades_from_drawings": detected,
        "overlap_with_drawings": overlap_with_drawings,
        "missing_from_drawings": missing_from_drawings,
    }


def build_spec_issues(spec_context: dict[str, Any]) -> list[dict[str, Any]]:
    missing = spec_context.get("missing_from_drawings", [])
    if not isinstance(missing, list) or not missing:
        return []
    source_sheets: list[str] = []
    return [
        {
            "message": (
                "Specification-derived trade requirements were found that are not clearly represented "
                "in detected drawing trades. Drawings remain authoritative; review these trades manually."
            ),
            "severity": "warning",
            "source_sheets": source_sheets,
            "missing_information": [str(item) for item in missing],
        }
    ]


def build_submittal_queries(
    *,
    spec_profiles: list[dict[str, Any]] | None,
    max_queries: int = 40,
) -> list[str]:
    profiles = spec_profiles or []
    queries: list[str] = []
    seen: set[str] = set()

    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        standard_name = str(profile.get("standard_name", "")).strip()
        refs = profile.get("detected_standard_refs", [])
        trades = profile.get("detected_trade_hints", [])
        refs_clean = [str(item).strip().upper() for item in refs if str(item).strip()]
        trades_clean = [str(item).strip() for item in trades if str(item).strip()]

        for ref in refs_clean:
            base = f"{ref} product submittal pdf"
            if base.lower() not in seen:
                seen.add(base.lower())
                queries.append(base)
                if len(queries) >= max_queries:
                    return queries
            for trade in trades_clean:
                combined = f"{trade} {ref} compliant product submittal pdf"
                if combined.lower() in seen:
                    continue
                seen.add(combined.lower())
                queries.append(combined)
                if len(queries) >= max_queries:
                    return queries

        if standard_name:
            base_name_query = f"{standard_name} approved submittal datasheet pdf"
            if base_name_query.lower() not in seen:
                seen.add(base_name_query.lower())
                queries.append(base_name_query)
                if len(queries) >= max_queries:
                    return queries

    return queries
