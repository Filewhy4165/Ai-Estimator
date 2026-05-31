from __future__ import annotations

import service.app as service_app
from service.spec_store import SpecStore


def test_specs_catalog_and_organizations(monkeypatch, tmp_path):
    store = SpecStore(str(tmp_path / "spec_store.json"))
    store.upsert_spec(
        {
            "spec_id": "spec-1",
            "title": "Federal Electrical Spec",
            "organization": "NASA",
            "agency": "NASA",
            "standard_name": "TSRC Electrical",
            "project_type": "federal",
            "tags": ["electrical"],
            "is_public": True,
            "source_file_name": "a.txt",
            "source_file_path": str(tmp_path / "a.txt"),
            "notes": "",
            "detected_standard_refs": ["NFPA 70"],
            "detected_trade_hints": ["electrical"],
            "text_excerpt": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    monkeypatch.setattr(service_app, "_spec_store", store)

    catalog = service_app.get_specs_catalog(organization="NASA").model_dump()
    assert catalog["total_returned"] >= 1
    assert any(item["organization"] == "NASA" for item in catalog["items"])

    orgs = service_app.get_specs_organizations().model_dump()
    assert "NASA" in orgs["organizations"]


def test_search_spec_submittals_returns_queries_when_web_disabled(monkeypatch, tmp_path):
    store = SpecStore(str(tmp_path / "spec_store.json"))
    store.upsert_spec(
        {
            "spec_id": "spec-x",
            "title": "Spec X",
            "organization": "Org",
            "agency": "Agency",
            "standard_name": "Spec X Std",
            "project_type": "commercial",
            "tags": [],
            "is_public": True,
            "source_file_name": "x.txt",
            "source_file_path": str(tmp_path / "x.txt"),
            "notes": "",
            "detected_standard_refs": ["ASTM C150"],
            "detected_trade_hints": ["structural"],
            "text_excerpt": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    monkeypatch.setattr(service_app, "_spec_store", store)
    monkeypatch.delenv("AI_ESTIMATOR_ENABLE_WEB_SUBMITTALS", raising=False)

    payload = service_app.search_spec_submittals(spec_profile_ids="spec-x").model_dump()
    assert payload["query_count"] > 0
    assert payload["web_lookup_enabled"] is False
    assert payload["items"] == []
