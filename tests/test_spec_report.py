from __future__ import annotations

from service.spec_report import build_spec_compliance_report


def test_build_spec_compliance_report_flags_missing_spec_trades() -> None:
    payload = build_spec_compliance_report(
        job_id="job-1",
        result={
            "spec_context": {
                "authority_order": ["drawings", "specifications", "assumptions"],
                "conflict_policy": "Drawings control.",
                "applied_spec_profiles": [
                    {
                        "spec_id": "spec-1",
                        "organization": "NASA",
                        "standard_name": "TSRC",
                        "project_type": "government-facilities",
                        "detected_standard_refs": ["NFPA 13"],
                        "detected_trade_hints": ["fire_protection"],
                        "is_public": True,
                    }
                ],
                "detected_standard_refs": ["NFPA 13"],
                "required_trades_from_specs": ["fire_protection"],
                "detected_trades_from_drawings": ["architectural"],
                "overlap_with_drawings": [],
                "missing_from_drawings": ["fire_protection"],
            }
        },
    )

    assert payload["status"] == "review_required"
    assert payload["missing_from_drawings"] == ["fire_protection"]
    assert payload["detected_standard_refs"] == ["NFPA 13"]
    assert payload["applied_spec_profiles"][0]["organization"] == "NASA"


def test_build_spec_compliance_report_handles_jobs_without_specs() -> None:
    payload = build_spec_compliance_report(job_id="job-2", result={})

    assert payload["status"] == "no_specs_applied"
    assert payload["applied_spec_count"] == 0
    assert payload["authority_order"] == ["drawings", "specifications", "assumptions"]
