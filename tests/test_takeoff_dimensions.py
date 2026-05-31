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
