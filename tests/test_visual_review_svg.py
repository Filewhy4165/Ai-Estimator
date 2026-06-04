from service.visual_review import (
    apply_scale_calibration_to_result,
    build_scale_calibration_preview,
    build_visual_evidence_svg,
    build_visual_measurement_page,
    list_visual_measurements,
    save_visual_measurements_to_result,
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
                "manual_visual_measurements": [
                    {
                        "id": "saved-1",
                        "label": "M1",
                        "sheet_id": "A101",
                        "source_page_index": 1,
                        "a": {"x": 10.0, "y": 20.0},
                        "b": {"x": 110.0, "y": 20.0},
                        "measured_pdf_units": 100.0,
                        "known_length_ft": 25.0,
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


def test_visual_measurement_page_embeds_svg_and_calibration_controls():
    page = build_visual_measurement_page(
        job_id="job-1",
        result=_result_with_vector_data(),
        sheet_id="A101",
        source_page_index=1,
        tenant_id="tenant-a",
        limit=10,
    )

    assert "<!doctype html>" in page
    assert "EstimateForge Visual Measurement" in page
    assert 'data-sheet-id="A101"' in page
    assert 'id="measuredPdfUnits"' in page
    assert 'id="knownLengthFt"' in page
    assert 'id="measurementList"' in page
    assert "Add Measurement" in page
    assert "Delete Selected" in page
    assert "window.addEventListener(\"pointermove\", updateDraggedEndpoint)" in page
    assert "drag either endpoint" in page.lower()
    assert "html, body { height: 100%; overflow: hidden; }" in page
    assert 'id="saveMeasurementsBtn"' in page
    assert "/visual-measurements" in page
    assert "saved-1" in page
    assert "hydrateSavedMeasurements" in page
    assert "/scale-calibration/preview" in page
    assert "/scale-calibration/apply" in page
    assert 'value="tenant-a"' in page
    assert "let points = []" not in page


def test_save_visual_measurements_persists_annotations_and_updates_takeoff():
    result = _result_with_vector_data()
    updated, payload = save_visual_measurements_to_result(
        result=result,
        sheet_id="A101",
        source_page_index=1,
        measurements=[
            {
                "id": "m-new",
                "label": "M2",
                "a": {"x": 0, "y": 0},
                "b": {"x": 30, "y": 40},
                "known_length_ft": 10,
            }
        ],
    )

    assert payload["measurement_count"] == 1
    saved = list_visual_measurements(result=updated, sheet_id="A101", source_page_index=1)
    assert saved == [
        {
            "id": "m-new",
            "label": "M2",
            "sheet_id": "A101",
            "source_page_index": 1,
            "trade": "manual_review",
            "measurement_type": "visual_length",
            "a": {"x": 0.0, "y": 0.0},
            "b": {"x": 30.0, "y": 40.0},
            "measured_pdf_units": 50.0,
            "known_length_ft": 10.0,
        }
    ]
    linear = updated["quantity_takeoff"]["linear"]
    assert linear["manual_visual_measurements_count"] == 1
    assert linear["manual_visual_measurements_total_pdf_units"] == 50.0
    assert linear["manual_visual_measurements_known_total_ft"] == 10.0
    assert updated is not result


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
