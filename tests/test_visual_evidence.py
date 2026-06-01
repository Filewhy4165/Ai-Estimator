from service.review_queue import build_visual_evidence


def test_build_visual_evidence_summarizes_vector_items():
    result = {
        "geometry": {
            "annotations": {
                "vector_pages": [{"sheet_id": "A101"}, {"sheet_id": "P101"}],
                "vector_measurements": [
                    {
                        "sheet_id": "A101",
                        "line_count": 2,
                        "rectangle_count": 1,
                        "total_linework_pdf_units": 100.0,
                    },
                    {
                        "sheet_id": "A101",
                        "line_count": 1,
                        "rectangle_count": 0,
                        "total_linework_pdf_units": 25.0,
                    },
                ],
                "vector_evidence": [
                    {"sheet_id": "A101", "kind": "line"},
                    {"sheet_id": "A101", "kind": "rectangle"},
                    {"sheet_id": "P101", "kind": "line"},
                ],
            }
        }
    }

    payload = build_visual_evidence(job_id="job-1", result=result, limit=2)

    assert payload["job_id"] == "job-1"
    assert payload["summary"]["vector_page_count"] == 2
    assert payload["summary"]["evidence_count"] == 3
    assert payload["summary"]["returned_count"] == 2
    assert payload["items"] == [
        {"sheet_id": "A101", "kind": "line"},
        {"sheet_id": "A101", "kind": "rectangle"},
    ]
    assert payload["summary"]["by_sheet"] == [
        {
            "sheet_id": "A101",
            "line_count": 3,
            "rectangle_count": 1,
            "total_linework_pdf_units": 125.0,
        }
    ]
