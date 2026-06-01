from ai_estimator.extractors.geometry import extract_geometry
from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


def _sheet(*, page_index: int, sheet_id: str) -> ClassifiedSheet:
    return ClassifiedSheet(
        sheet_id=sheet_id,
        sheet_id_source="detected",
        title="Test",
        sheet_type="plan",
        trade="architectural",
        confidence=0.9,
        source_page_index=page_index,
        source_pdf="x.pdf",
    )


def test_geometry_room_extraction_filters_schedule_noise():
    text = "\n".join(
        [
            "NAME ROOM FLOOR BASE WALLS CEILING",
            "ROOM WASH 114 MEN 115 BREAK RM 122 OFFICE 122A",
            "MEN ROOM 115",
            "ROOM 102",
        ]
    )
    pages = [LoadedPage(page_index=0, source_pdf="x.pdf", text=text)]
    sheets = [_sheet(page_index=0, sheet_id="A101")]

    geometry, _ = extract_geometry(pages, sheets)
    rooms = geometry.get("annotations", {}).get("rooms", [])
    room_names = [row.get("name") for row in rooms if isinstance(row, dict)]

    assert "MEN 115" in room_names
    assert "102" in room_names
    assert not any("WASH 114 MEN 115 BREAK RM 122 OFFICE 122A" == name for name in room_names)
    assert not any("NAME ROOM FLOOR BASE WALLS CEILING" == name for name in room_names)


def test_geometry_dimension_extraction_skips_scale_and_dedupes():
    text = "\n".join(
        [
            "SCALE: 1/8\" = 1'-0\"",
            "CLEAR WIDTH 6'-0\"",
            "CLEAR WIDTH 6'-0\"",
        ]
    )
    pages = [LoadedPage(page_index=0, source_pdf="x.pdf", text=text)]
    sheets = [_sheet(page_index=0, sheet_id="A101")]

    geometry, _ = extract_geometry(pages, sheets)
    dimensions = geometry.get("annotations", {}).get("dimensions", [])
    values = [row.get("value") for row in dimensions if isinstance(row, dict)]

    assert "6'-0\"" in values
    assert "1'-0\"" not in values
    assert values.count("6'-0\"") == 1


def test_geometry_dimension_extraction_normalizes_spacing():
    text = "\n".join(
        [
            "CLEARANCE 2' - 11\"",
            "CLEARANCE 2'-11\"",
        ]
    )
    pages = [LoadedPage(page_index=0, source_pdf="x.pdf", text=text)]
    sheets = [_sheet(page_index=0, sheet_id="A101")]

    geometry, _ = extract_geometry(pages, sheets)
    dimensions = geometry.get("annotations", {}).get("dimensions", [])
    values = [row.get("value") for row in dimensions if isinstance(row, dict)]

    assert values.count("2'-11\"") == 1


def test_geometry_extracts_vector_evidence_annotations():
    pages = [
        LoadedPage(
            page_index=0,
            source_pdf="x.pdf",
            text="",
            width=200,
            height=100,
            vector_primitives=[
                {
                    "kind": "line",
                    "points": [[10, 10], [110, 10]],
                    "bbox": [10, 10, 110, 10],
                    "length_pdf_units": 100.0,
                },
                {
                    "kind": "rectangle",
                    "points": [[20, 20], [50, 20], [50, 60], [20, 60]],
                    "bbox": [20, 20, 50, 60],
                    "perimeter_pdf_units": 140.0,
                },
            ],
        )
    ]
    sheets = [_sheet(page_index=0, sheet_id="A101")]

    geometry, issues = extract_geometry(pages, sheets)
    annotations = geometry.get("annotations", {})

    assert annotations["vector_pages"][0]["primitive_count"] == 2
    assert annotations["vector_measurements"][0]["total_linework_pdf_units"] == 240.0
    assert len(annotations["vector_evidence"]) == 2
    assert any("Vector linework was extracted" in issue for issue in issues)
