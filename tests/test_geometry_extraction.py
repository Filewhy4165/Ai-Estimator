from ai_estimator.extractors.geometry import extract_geometry
from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


def _sheet(*, page_index: int, sheet_id: str) -> ClassifiedSheet:
    return ClassifiedSheet(
        sheet_id=sheet_id,
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

    assert "6'-0" in values
    assert "1'-0" not in values
    assert values.count("6'-0") == 1
