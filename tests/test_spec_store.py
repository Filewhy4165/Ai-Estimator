from pathlib import Path

from service.spec_store import SpecStore, build_spec_profile_from_file


def test_spec_store_seeds_and_lists_profiles(tmp_path: Path):
    store = SpecStore(str(tmp_path / "spec_store.json"))
    items, total = store.list_specs(limit=50, offset=0)
    assert total >= 1
    assert any(item.get("spec_id") == "seed-nasa-tsrc" for item in items)


def test_spec_store_upsert_and_get_by_id(tmp_path: Path):
    store = SpecStore(str(tmp_path / "spec_store.json"))
    profile = {
        "spec_id": "spec-abc",
        "title": "Project Spec",
        "organization": "Test Org",
        "agency": "Test Agency",
        "standard_name": "Spec 01",
        "project_type": "commercial",
        "tags": ["hvac"],
        "is_public": True,
        "source_file_name": "spec.txt",
        "source_file_path": "C:/tmp/spec.txt",
        "notes": "",
        "detected_standard_refs": ["NFPA 70"],
        "detected_trade_hints": ["electrical"],
        "text_excerpt": "excerpt",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    store.upsert_spec(profile)
    loaded = store.get_spec("spec-abc")
    assert loaded is not None
    assert loaded["organization"] == "Test Org"


def test_build_spec_profile_from_file_detects_refs(tmp_path: Path):
    spec_file = tmp_path / "spec.txt"
    spec_file.write_text(
        "Electrical work shall comply with NFPA 70 and ASTM C150 where applicable.",
        encoding="utf-8",
    )
    profile = build_spec_profile_from_file(
        file_path=str(spec_file),
        title="Spec File",
        organization="Org",
        agency="Agency",
        standard_name="Spec",
        project_type="industrial",
        tags=["test"],
        notes="note",
        is_public=True,
    )
    assert "NFPA 70" in profile["detected_standard_refs"]
    assert "electrical" in profile["detected_trade_hints"]
