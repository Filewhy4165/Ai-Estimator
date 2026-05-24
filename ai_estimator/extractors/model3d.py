from __future__ import annotations


def build_simplified_model(geometry: dict[str, object], model_format: str = "JSON-geometry") -> dict[str, object]:
    elements: list[dict[str, object]] = []

    for bucket in ("walls", "doors", "windows", "slabs", "roofs", "fixtures", "equipment"):
        for item in geometry.get(bucket, []):  # type: ignore[arg-type]
            if not isinstance(item, dict):
                continue
            elements.append(
                {
                    "id": f"Model_{item.get('id')}",
                    "type": item.get("type", bucket.rstrip("s")),
                    "source_element_id": item.get("id"),
                    "geometry": item.get("geometry", {}),
                }
            )

    return {"format": model_format, "elements": elements}

