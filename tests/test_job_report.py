from __future__ import annotations

from service.job_report import build_job_report_html


def test_build_job_report_html_renders_estimator_sections() -> None:
    html = build_job_report_html(
        job_id="job-123",
        status="completed",
        created_at="2026-06-01T00:00:00+00:00",
        updated_at="2026-06-01T00:01:00+00:00",
        completed_at="2026-06-01T00:02:00+00:00",
        input_payload={
            "analysis_mode": "all",
            "selected_trades": ["mechanical_hvac"],
            "uploaded_files": [{"file_name": "drawings.pdf"}],
        },
        result={
            "sheets_detected": [
                {
                    "source_page_index": 1,
                    "sheet_id": "M101",
                    "title": "MECHANICAL PLAN",
                    "discipline": "mechanical_hvac",
                    "sheet_type": "plan",
                    "confidence": 0.91,
                }
            ],
            "trade_scope": {
                "requested_mode": "all",
                "detected_trades": ["mechanical_hvac"],
                "analyzed_trades": ["mechanical_hvac"],
                "skipped_trades": [],
            },
            "quantity_takeoff": {
                "linear": {"duct_ft": 42.5},
                "counts": {"diffuser": 6},
                "by_trade": {
                    "mechanical_hvac": {
                        "linear": {"duct_ft": 42.5},
                        "counts": {"diffuser": 6},
                    }
                },
            },
            "cost_mapping": {
                "cost_codes": {
                    "csi_masterformat": {"mechanical_hvac": ["23"]}
                }
            },
            "issues_or_ambiguities": [{"severity": "warning", "message": "Scale needs review."}],
        },
    )

    assert "Estimator Report" in html
    assert "M101" in html
    assert "MECHANICAL PLAN" in html
    assert "duct_ft" in html
    assert "Scale needs review." in html
    assert "23" in html
