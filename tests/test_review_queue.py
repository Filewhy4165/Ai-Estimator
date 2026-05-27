from service.review_queue import (
    build_benchmark_manifest_template,
    build_review_queue,
    build_sheet_overrides_template,
)


def test_review_queue_flags_unmapped_low_confidence_and_missing_scale():
    result = {
        "sheets_detected": [
            {
                "sheet_id": "UNMAPPED_doc_3",
                "title": "Untitled Sheet",
                "confidence": 0.42,
                "source_page_index": 3,
                "discipline": "other",
            },
            {
                "sheet_id": "A101",
                "title": "Floor Plan",
                "confidence": 0.91,
                "source_page_index": 1,
                "discipline": "architectural",
            },
        ],
        "scale_analysis": {
            "by_sheet": [
                {"sheet_id": "UNMAPPED_doc_3", "detected_scale": None},
                {"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\""},
            ]
        },
        "legend_and_symbols": {
            "unknown_symbols": [
                {"sheet_id": "UNMAPPED_doc_3", "symbol": "P-1"},
                {"sheet_id": "UNMAPPED_doc_3", "symbol": "P-2"},
            ]
        },
    }
    queue = build_review_queue(
        job_id="job-1", result=result, low_confidence_threshold=0.75, include_only_flagged=True
    )

    assert queue["summary"]["total_sheets"] == 2
    assert queue["summary"]["flagged_sheets"] == 1
    assert queue["summary"]["sheet_id_source_counts"] == {"detected": 1, "unmapped": 1}
    assert len(queue["items"]) == 1
    item = queue["items"][0]
    assert item["sheet_id_source"] == "unmapped"
    codes = {flag["code"] for flag in item["flags"]}
    assert "unmapped_sheet_id" in codes
    assert "low_confidence_classification" in codes
    assert "missing_scale" in codes
    assert item["unknown_symbol_count"] == 2


def test_review_queue_include_all_sheets():
    result = {
        "sheets_detected": [
            {"sheet_id": "A101", "title": "Floor Plan", "confidence": 0.91, "source_page_index": 1}
        ],
        "scale_analysis": {"by_sheet": [{"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\""}]},
        "legend_and_symbols": {"unknown_symbols": []},
    }
    queue = build_review_queue(
        job_id="job-2", result=result, low_confidence_threshold=0.75, include_only_flagged=False
    )
    assert queue["summary"]["total_sheets"] == 1
    assert len(queue["items"]) == 1
    assert queue["items"][0]["sheet_id"] == "A101"
    assert queue["items"][0]["sheet_id_source"] == "detected"
    assert queue["items"][0]["flags"] == []


def test_review_queue_flags_inferred_sheet_id_from_pipeline_issue():
    result = {
        "sheets_detected": [
            {
                "sheet_id": "FAC-4476-A1",
                "title": "Floor Plan",
                "confidence": 0.62,
                "source_page_index": 2,
                "discipline": "architectural",
            }
        ],
        "scale_analysis": {"by_sheet": [{"sheet_id": "FAC-4476-A1", "detected_scale": "1/8\" = 1'-0\""}]},
        "legend_and_symbols": {"unknown_symbols": []},
        "issues_or_ambiguities": [
            {
                "message": (
                    "Some sheet IDs were inferred from building number + short sheet token. "
                    "Review these IDs before final estimate handoff."
                ),
                "severity": "warning",
                "source_sheets": ["FAC-4476-A1"],
            }
        ],
    }
    queue = build_review_queue(
        job_id="job-inferred", result=result, low_confidence_threshold=0.75, include_only_flagged=True
    )

    assert queue["summary"]["flagged_sheets"] == 1
    assert queue["summary"]["reason_counts"]["inferred_sheet_id_requires_review"] == 1
    assert queue["summary"]["sheet_id_source_counts"] == {"inferred_facility_short": 1}
    assert len(queue["items"]) == 1
    assert queue["items"][0]["sheet_id_source"] == "inferred_facility_short"
    codes = {flag["code"] for flag in queue["items"][0]["flags"]}
    assert "inferred_sheet_id_requires_review" in codes


def test_review_queue_flags_inferred_sheet_id_from_sheet_source_field():
    result = {
        "sheets_detected": [
            {
                "sheet_id": "FAC-4476-A1",
                "sheet_id_source": "inferred_facility_short",
                "title": "Floor Plan",
                "confidence": 0.62,
                "source_page_index": 2,
                "discipline": "architectural",
            }
        ],
        "scale_analysis": {"by_sheet": [{"sheet_id": "FAC-4476-A1", "detected_scale": "1/8\" = 1'-0\""}]},
        "legend_and_symbols": {"unknown_symbols": []},
        "issues_or_ambiguities": [],
    }
    queue = build_review_queue(
        job_id="job-inferred-source", result=result, low_confidence_threshold=0.75, include_only_flagged=True
    )
    assert len(queue["items"]) == 1
    assert queue["items"][0]["sheet_id_source"] == "inferred_facility_short"
    codes = {flag["code"] for flag in queue["items"][0]["flags"]}
    assert "inferred_sheet_id_requires_review" in codes


def test_sheet_overrides_template_returns_only_problem_rows_by_default():
    result = {
        "sheets_detected": [
            {
                "sheet_id": "UNMAPPED_doc_3",
                "title": "Untitled Sheet",
                "source_page_index": 3,
            },
            {
                "sheet_id": "A101",
                "title": "Floor Plan",
                "source_page_index": 1,
            },
            {
                "sheet_id": "FLOOR PLANS, SCHEDULE AND NOTES",
                "title": "",
                "source_page_index": 2,
            },
        ]
    }
    payload = build_sheet_overrides_template(job_id="job-3", result=result, include_all=False)

    assert payload["summary"]["total_sheets"] == 3
    assert payload["summary"]["rows_returned"] == 2
    assert payload["summary"]["unmapped_count"] == 1
    assert payload["summary"]["sheet_id_source_counts"] == {"detected": 2, "unmapped": 1}
    assert [row["source_page_index"] for row in payload["items"]] == [2, 3]
    assert payload["items"][0]["current_sheet_id_source"] == "detected"
    assert payload["items"][0]["reason"] == "invalid_sheet_id_format"
    assert payload["items"][0]["sheet_id"] == ""
    assert payload["items"][1]["current_sheet_id_source"] == "unmapped"
    assert payload["items"][1]["reason"] == "unmapped_sheet_id"
    assert payload["items"][1]["title"] == ""


def test_sheet_overrides_template_includes_inferred_sheet_ids_by_default():
    result = {
        "sheets_detected": [
            {"sheet_id": "FAC-4476-A1", "title": "Floor Plan", "source_page_index": 2},
            {"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 1},
        ],
        "issues_or_ambiguities": [
            {
                "message": (
                    "Some sheet IDs were inferred from building number + short sheet token. "
                    "Review these IDs before final estimate handoff."
                ),
                "severity": "warning",
                "source_sheets": ["FAC-4476-A1"],
            }
        ],
    }
    payload = build_sheet_overrides_template(job_id="job-3b", result=result, include_all=False)
    assert payload["summary"]["rows_returned"] == 1
    assert payload["summary"]["inferred_sheet_id_count"] == 1
    assert payload["summary"]["sheet_id_source_counts"] == {"detected": 1, "inferred_facility_short": 1}
    assert payload["items"][0]["current_sheet_id"] == "FAC-4476-A1"
    assert payload["items"][0]["current_sheet_id_source"] == "inferred_facility_short"
    assert payload["items"][0]["reason"] == "inferred_sheet_id_requires_review"
    assert payload["items"][0]["sheet_id"] == ""


def test_sheet_overrides_template_includes_inferred_sheet_ids_from_source_field():
    result = {
        "sheets_detected": [
            {
                "sheet_id": "FAC-4476-A1",
                "sheet_id_source": "inferred_facility_short",
                "title": "Floor Plan",
                "source_page_index": 2,
            },
            {"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 1},
        ],
        "issues_or_ambiguities": [],
    }
    payload = build_sheet_overrides_template(job_id="job-3c", result=result, include_all=False)
    assert payload["summary"]["rows_returned"] == 1
    assert payload["summary"]["inferred_sheet_id_count"] == 1
    assert payload["summary"]["sheet_id_source_counts"] == {"detected": 1, "inferred_facility_short": 1}
    assert payload["items"][0]["current_sheet_id"] == "FAC-4476-A1"
    assert payload["items"][0]["current_sheet_id_source"] == "inferred_facility_short"
    assert payload["items"][0]["reason"] == "inferred_sheet_id_requires_review"


def test_sheet_overrides_template_include_all():
    result = {
        "sheets_detected": [
            {"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 1},
            {"sheet_id": "A102", "title": "Reflected Ceiling Plan", "source_page_index": 2},
        ]
    }
    payload = build_sheet_overrides_template(job_id="job-4", result=result, include_all=True)
    assert payload["summary"]["rows_returned"] == 2
    assert payload["items"][0]["sheet_id"] == "A101"
    assert payload["items"][1]["sheet_id"] == "A102"


def test_benchmark_manifest_template_uses_job_input_and_filters_unmapped():
    result = {
        "sheets_detected": [
            {"sheet_id": "A101", "title": "Floor Plan", "source_page_index": 1},
            {"sheet_id": "UNMAPPED_doc_2", "title": "Untitled Sheet", "source_page_index": 2},
            {"sheet_id": "E121", "title": "Electrical Plan", "source_page_index": 3},
        ],
        "scale_analysis": {
            "by_sheet": [
                {"sheet_id": "A101", "detected_scale": "1/8\" = 1'-0\"", "confidence": 0.7},
                {"sheet_id": "E121", "detected_scale": "1:100", "confidence": 0.9},
            ]
        },
        "trade_scope": {"analyzed_trades": ["architectural", "electrical"]},
        "quantity_takeoff": {"counts": {"door": 2, "window": 1}},
        "legend_and_symbols": {"unknown_symbols": []},
    }
    job_input = {
        "analysis_mode": "selected",
        "selected_trades": ["architectural", "electrical"],
        "sheet_overrides": [{"source_page_index": 2, "sheet_id": "A102", "title": "Second Floor Plan"}],
        "notes": "Prioritize restroom scope.",
        "uploaded_files": [{"path": "C:/drawings/set1.pdf"}],
    }
    payload = build_benchmark_manifest_template(
        job_id="job-5",
        result=result,
        job_input=job_input,
        include_unmapped=False,
        case_id="case-001",
    )

    assert payload["summary"]["total_sheets"] == 3
    assert payload["summary"]["candidate_sheet_ids"] == 2
    assert payload["summary"]["excluded_unmapped_count"] == 1
    assert payload["summary"]["source_total_count"] == 3

    manifest = payload["manifest"]
    assert manifest["defaults"]["analysis_mode"] == "selected"
    assert manifest["defaults"]["selected_trades"] == ["architectural", "electrical"]
    assert manifest["defaults"]["notes"] == "Prioritize restroom scope."
    assert manifest["cases"][0]["case_id"] == "case-001"
    assert manifest["cases"][0]["pdf_paths"] == ["C:/drawings/set1.pdf"]
    assert manifest["cases"][0]["expected"]["sheet_ids"] == ["A101", "E121"]
    assert manifest["cases"][0]["expected"]["scales_by_sheet"] == {
        "A101": "1/8\" = 1'-0\"",
        "E121": "1:100",
    }
    assert manifest["cases"][0]["expected"]["analyzed_trades"] == ["architectural", "electrical"]
    assert manifest["cases"][0]["expected"]["quantity_sanity"] == {
        "require_nonempty_counts": True,
        "min_total_count": 3,
    }


def test_benchmark_manifest_template_can_include_unmapped():
    result = {
        "sheets_detected": [
            {"sheet_id": "UNMAPPED_doc_1", "source_page_index": 1},
            {"sheet_id": "A101", "source_page_index": 2},
        ],
        "scale_analysis": {"by_sheet": []},
        "trade_scope": {"analyzed_trades": []},
        "quantity_takeoff": {"counts": {}},
        "legend_and_symbols": {"unknown_symbols": []},
    }
    payload = build_benchmark_manifest_template(
        job_id="job-6",
        result=result,
        job_input={"uploaded_files": []},
        include_unmapped=True,
    )
    sheet_ids = payload["manifest"]["cases"][0]["expected"]["sheet_ids"]
    assert sheet_ids == ["UNMAPPED_doc_1", "A101"]
    assert payload["manifest"]["cases"][0]["expected"]["quantity_sanity"] == {
        "require_nonempty_counts": False,
        "min_total_count": 0,
    }
