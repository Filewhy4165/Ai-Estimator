from ai_estimator.extractors.takeoff import compute_quantity_takeoff


def test_compute_quantity_takeoff_summarizes_explicit_dimensions():
    geometry = {
        "walls": [],
        "doors": [],
        "windows": [],
        "slabs": [],
        "roofs": [],
        "fixtures": [],
        "equipment": [],
        "annotations": {
            "dimensions": [
                {"sheet_id": "A101", "trade": "architectural", "value": "10'-6\""},
                {"sheet_id": "P101", "trade": "plumbing", "value": "3'-0\""},
                {"sheet_id": "P101", "trade": "plumbing", "value": "bad"},
            ]
        },
    }

    takeoff, issues = compute_quantity_takeoff(geometry)

    assert takeoff["linear"]["explicit_dimensions_total_ft"] == 13.5
    assert takeoff["linear"]["explicit_dimensions_count"] == 2
    assert takeoff["linear"]["explicit_dimensions_by_sheet_ft"] == {
        "A101": 10.5,
        "P101": 3.0,
    }
    assert takeoff["by_trade"]["architectural"]["linear"]["explicit_dimensions_total_ft"] == 10.5
    assert takeoff["by_trade"]["plumbing"]["linear"]["explicit_dimensions_count"] == 1
    assert any("reference linear measurements" in item for item in issues)


def test_compute_quantity_takeoff_rejects_invalid_inches():
    geometry = {
        "annotations": {
            "dimensions": [{"sheet_id": "A101", "trade": "architectural", "value": "1'-12\""}]
        }
    }

    takeoff, issues = compute_quantity_takeoff(geometry)

    assert takeoff["linear"] == {}
    assert "Linear quantities are empty; no reliable lengths were extracted." in issues


def test_compute_quantity_takeoff_summarizes_scaled_vector_linework():
    geometry = {
        "annotations": {
            "vector_measurements": [
                {
                    "sheet_id": "A101",
                    "trade": "architectural",
                    "line_count": 1,
                    "rectangle_count": 1,
                    "total_linework_pdf_units": 72.0,
                },
                {
                    "sheet_id": "P101",
                    "trade": "plumbing",
                    "line_count": 1,
                    "rectangle_count": 0,
                    "total_linework_pdf_units": 36.0,
                },
            ]
        }
    }
    scale_analysis = {
        "by_sheet": [
            {
                "sheet_id": "A101",
                "detected_scale": "1/8\" = 1'-0\"",
                "units": "imperial",
                "confidence": 0.75,
            }
        ]
    }

    takeoff, issues = compute_quantity_takeoff(geometry, scale_analysis=scale_analysis)

    assert takeoff["linear"]["vector_linework_total_pdf_units"] == 108.0
    assert takeoff["linear"]["vector_linework_total_ft"] == 8.0
    assert takeoff["linear"]["vector_linework_by_sheet_ft"] == {"A101": 8.0}
    assert takeoff["by_trade"]["architectural"]["linear"]["vector_linework_total_ft"] == 8.0
    assert takeoff["by_trade"]["plumbing"]["linear"]["vector_linework_total_pdf_units"] == 36.0
    assert any("Vector linework was measured" in item for item in issues)
    assert any("P101" in item for item in issues)
