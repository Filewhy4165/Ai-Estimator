from __future__ import annotations

import json
from pathlib import Path


def validate_output(payload: dict[str, object], schema_path: str) -> tuple[bool, list[str]]:
    try:
        import jsonschema  # type: ignore
    except Exception:
        return False, ["jsonschema dependency not available."]

    path = Path(schema_path)
    if not path.exists():
        return False, [f"Schema file not found: {schema_path}"]

    with path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return True, []

    messages = []
    for err in errors:
        path_text = ".".join(str(x) for x in err.path) or "<root>"
        messages.append(f"{path_text}: {err.message}")
    return False, messages

