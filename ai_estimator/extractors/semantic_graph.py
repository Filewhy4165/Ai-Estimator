from __future__ import annotations


def build_semantic_graph(geometry: dict[str, object]) -> dict[str, object]:
    elements: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []

    for bucket in ("walls", "doors", "windows", "slabs", "roofs", "fixtures", "equipment"):
        for item in geometry.get(bucket, []):  # type: ignore[arg-type]
            if not isinstance(item, dict):
                continue
            elements.append(
                {
                    "id": item.get("id"),
                    "type": item.get("type", bucket.rstrip("s")),
                    "trade": item.get("trade", "other"),
                    "properties": item.get("properties", {}),
                    "geometry": item.get("geometry", {}),
                    "relationships": item.get("relationships", []),
                }
            )

    # Build explicit relation objects from element relationship id references.
    ids = {str(el.get("id")) for el in elements}
    for el in elements:
        source_id = str(el.get("id"))
        for rel in el.get("relationships", []):
            rel_id = str(rel)
            if rel_id in ids:
                relationships.append({"from": source_id, "to": rel_id, "type": "related_to"})

    return {"elements": elements, "relationships": relationships}

