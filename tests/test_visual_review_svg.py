from service.visual_review import (
    apply_scale_calibration_to_result,
    build_scale_calibration_preview,
    build_visual_evidence_svg,
)


def _result_with_vector_data():
    return {
        "geometry": {
            "annotations": {
                "vector_pages": [
                    {
                        "sheet_id": "A101",
                        "source_page_index": 1,
                        "page_width_pdf_units": 200,
                        "page_height_pdf_units": 100,
                    }
                ],
                "vector_evidence": [
                    {
                        "sheet_id": "A101",
                        "source_page_index": 1,
                        "kind": "line",
                        "points": [[10, 10], [110, 10]],
                        "line_width": 0.5,
                    },
                    {
                        "sheet_id": "A101",
                        "source_page_index": 1,
                        "kind": "rectangle",
                        "points": [[20, 20], [50, 20], [50, 60], [20, 60]],
                        "line_width": 0.5,
                    },
                    {
                        "sheet_id": "P101",
                        "source_page_index": 2,
                        "kind": "line",
                        "points": [[1, 1], [2, 2]],
                    },
                ],
                "vector_measurements": [
                    {
                        "sheet_id": "A101",
                        "source_page_index": 1,
                        "line_count": 1,
                        "rectangle_count": 1,
                        "line_length_pdf_units": 100.0,
                        "rectangle_perimeter_pdf_units": 140.0,
                        "total_linework_pdf_units": 240.0,
                    }
                ],
            }
        }
    }


def test_visual_evidence_svg_renders_selected_sheet_page():
    svg = build_visual_evidence_svg(
        job_id="job-1",
        result=_result_with_vector_data(),
        sheet_id="A101",
        source_page_index=1,
        limit=10,
    )

    assert svg.startswith('<?xml version="1.0"')
    assert "<svg" in svg
    assert 'data-job-id="job-1"' in svg
    assert 'data-sheet-id="A101"' in svg
    assert "Sheet A101" in svg
    assert "<polyline" in svg
    assert "<polygon" in svg
    assert "P101" not in svg


def test_visual_evidence_svg_limits_evidence_items():
    svg = build_visual_evidence_svg(
        job_id="job-1",
        result=_result_with_vector_data(),
        sheet_id="A101",
        source_page_index=1,
        limit=1,
    )

    assert svg.count("<polyline") + svg.count("<polygon") == 1
    assert "Evidence 1" in svg


def test_scale_calibration_preview_converts_vector_units_to_feet():
    payload = build_scale_calibration_preview(
        job_id="job-1",
        result=_result_with_vector_data(),
        sheet_id="A101",
        measured_pdf_units=50.0,
        known_length_ft=25.0,
    )

    assert payload["calibration"]["feet_per_pdf_unit"] == 0.5
    assert payload["calibration"]["pdf_units_per_foot"] == 2.0
    assert payload["preview"]["total_linework_pdf_units"] == 240.0
    assert payload["preview"]["calibrated_vector_linework_total_ft"] == 120.0
    assert payload["warnings"] == []


def test_apply_scale_calibration_updates_quantity_takeoff_result_copy():
    result = _result_with_vector_data()
    updated, payload = apply_scale_calibration_to_result(
        result=result,
        sheet_id="A101",
        measured_pdf_units=50.0,
        known_length_ft=25.0,
    )

    assert payload["applied"] is True
    assert payload["calibration"]["feet_per_pdf_unit"] == 0.5
    assert updated is not result
    assert result.get("quantity_takeoff") is None
    linear = updated["quantity_takeoff"]["linear"]
    assert linear["vector_linework_total_pdf_units"] == 240.0
    assert linear["vector_linework_total_ft"] == 120.0
    manual = updated["scale_analysis"]["manual_calibrations"][0]
    assert manual["sheet_id"] == "A101"
    assert manual["scale_source"] == "manual_calibration"
