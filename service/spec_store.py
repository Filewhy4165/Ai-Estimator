from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from pypdf import PdfReader

from ai_estimator.spec_intel import extract_standard_references, extract_trade_hints


PUBLIC_SPEC_TENANT_ID = "public"
DEFAULT_PRIVATE_SPEC_TENANT_ID = "default"


class SpecStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(Path(db_path))
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._ensure_seed_data()

    def list_specs(
        self,
        *,
        organization: str | None = None,
        agency: str | None = None,
        public_only: bool = True,
        project_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        payload = self._read_payload()
        specs = payload.get("items", [])
        if not isinstance(specs, list):
            specs = []

        org_filter = (organization or "").strip().lower()
        agency_filter = (agency or "").strip().lower()
        project_filter = (project_type or "").strip().lower()

        filtered: list[dict[str, Any]] = []
        for raw in specs:
            if not isinstance(raw, dict):
                continue
            if public_only:
                if not bool(raw.get("is_public", False)):
                    continue
            elif not _spec_visible_to_tenant(raw, tenant_id=tenant_id):
                continue
            org_value = str(raw.get("organization", "")).strip().lower()
            agency_value = str(raw.get("agency", "")).strip().lower()
            project_value = str(raw.get("project_type", "")).strip().lower()
            if org_filter and org_filter not in org_value:
                continue
            if agency_filter and agency_filter not in agency_value:
                continue
            if project_filter and project_filter not in project_value:
                continue
            filtered.append(raw)

        filtered.sort(
            key=lambda item: (
                str(item.get("organization", "")).lower(),
                str(item.get("standard_name", "")).lower(),
                str(item.get("title", "")).lower(),
            )
        )
        total = len(filtered)
        normalized_offset = max(0, offset)
        normalized_limit = max(1, min(limit, 500))
        return filtered[normalized_offset : normalized_offset + normalized_limit], total

    def get_spec(
        self,
        spec_id: str,
        *,
        tenant_id: str | None = None,
        include_public: bool = True,
    ) -> dict[str, Any] | None:
        target_id = spec_id.strip()
        if not target_id:
            return None
        payload = self._read_payload()
        specs = payload.get("items", [])
        if not isinstance(specs, list):
            return None
        for raw in specs:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("spec_id", "")).strip() == target_id:
                if not _spec_visible_to_tenant(
                    raw,
                    tenant_id=tenant_id,
                    include_public=include_public,
                ):
                    return None
                return raw
        return None

    def upsert_spec(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self._read_payload()
            specs = payload.get("items", [])
            if not isinstance(specs, list):
                specs = []

            spec_id = str(item.get("spec_id", "")).strip()
            if not spec_id:
                spec_id = str(uuid.uuid4())
                item["spec_id"] = spec_id
                item["created_at"] = _utc_now()

            item["tenant_id"] = _resolve_item_tenant_id(item)
            item["updated_at"] = _utc_now()
            stored = dict(item)
            updated_items: list[dict[str, Any]] = []
            replaced = False
            for raw in specs:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("spec_id", "")).strip() == spec_id:
                    updated_items.append(stored)
                    replaced = True
                else:
                    updated_items.append(raw)
            if not replaced:
                updated_items.append(stored)
            payload["items"] = updated_items
            payload["updated_at"] = _utc_now()
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return stored

    def get_by_ids(
        self,
        spec_ids: list[str],
        *,
        tenant_id: str | None = None,
        include_public: bool = True,
    ) -> list[dict[str, Any]]:
        wanted = {token.strip() for token in spec_ids if token.strip()}
        if not wanted:
            return []
        payload = self._read_payload()
        specs = payload.get("items", [])
        if not isinstance(specs, list):
            return []
        matched: list[dict[str, Any]] = []
        for raw in specs:
            if not isinstance(raw, dict):
                continue
            spec_id = str(raw.get("spec_id", "")).strip()
            if spec_id in wanted and _spec_visible_to_tenant(
                raw,
                tenant_id=tenant_id,
                include_public=include_public,
            ):
                matched.append(raw)
        return matched

    def list_organizations(self, *, tenant_id: str | None = None) -> list[str]:
        payload = self._read_payload()
        specs = payload.get("items", [])
        if not isinstance(specs, list):
            return []
        orgs = {
            str(raw.get("organization", "")).strip()
            for raw in specs
            if isinstance(raw, dict)
            and str(raw.get("organization", "")).strip()
            and _spec_visible_to_tenant(raw, tenant_id=tenant_id)
        }
        return sorted(orgs, key=lambda value: value.casefold())

    def _read_payload(self) -> dict[str, Any]:
        if not self._path.exists():
            return {
                "version": 1,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "items": [],
            }
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        if not isinstance(loaded, dict):
            loaded = {}
        if not isinstance(loaded.get("items"), list):
            loaded["items"] = []
        if "version" not in loaded:
            loaded["version"] = 1
        if "created_at" not in loaded:
            loaded["created_at"] = _utc_now()
        if "updated_at" not in loaded:
            loaded["updated_at"] = _utc_now()
        return loaded

    def _ensure_seed_data(self) -> None:
        if self._path.exists():
            return
        seed_items = [
            {
                "spec_id": "seed-nasa-tsrc",
                "title": "NASA Technical Standards Reference Collection (TSRC)",
                "organization": "NASA",
                "agency": "NASA",
                "standard_name": "TSRC",
                "project_type": "government-facilities",
                "tags": ["nasa", "tsrc", "federal"],
                "is_public": True,
                "tenant_id": PUBLIC_SPEC_TENANT_ID,
                "source_file_name": "",
                "source_file_path": "",
                "notes": "Seed profile for standards-aware estimating.",
                "detected_standard_refs": ["NASA-STD"],
                "detected_trade_hints": [],
                "text_excerpt": "",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
        ]
        payload = {
            "version": 1,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "items": seed_items,
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def extract_spec_text(file_path: str, *, max_chars: int = 20000) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            reader = PdfReader(str(path))
            pages = reader.pages[:40]
            chunks: list[str] = []
            for page in pages:
                text = page.extract_text() or ""
                if text:
                    chunks.append(text)
                    if sum(len(item) for item in chunks) >= max_chars:
                        break
            merged = "\n".join(chunks)
            return merged[:max_chars]
        except Exception:
            pass
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        raw = path.read_bytes().decode("utf-8", errors="ignore")
    return raw[:max_chars]


def build_spec_profile_from_file(
    *,
    file_path: str,
    title: str,
    organization: str,
    agency: str | None,
    standard_name: str | None,
    project_type: str | None,
    tags: list[str],
    notes: str | None,
    is_public: bool,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    text = extract_spec_text(file_path)
    refs = extract_standard_references(text)
    trade_hints = extract_trade_hints(text)
    excerpt = " ".join(text.split())[:1000]
    now = _utc_now()
    return {
        "spec_id": str(uuid.uuid4()),
        "title": title.strip() or Path(file_path).stem,
        "organization": organization.strip(),
        "agency": (agency or "").strip(),
        "standard_name": (standard_name or "").strip(),
        "project_type": (project_type or "").strip(),
        "tags": sorted({tag.strip() for tag in tags if tag.strip()}),
        "is_public": bool(is_public),
        "tenant_id": _normalize_spec_tenant_id(
            PUBLIC_SPEC_TENANT_ID if is_public else tenant_id
        ),
        "source_file_name": Path(file_path).name,
        "source_file_path": str(file_path),
        "notes": (notes or "").strip(),
        "detected_standard_refs": refs,
        "detected_trade_hints": trade_hints,
        "text_excerpt": excerpt,
        "created_at": now,
        "updated_at": now,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_item_tenant_id(item: dict[str, Any]) -> str:
    existing = str(item.get("tenant_id", "")).strip()
    if existing:
        return _normalize_spec_tenant_id(existing)
    if bool(item.get("is_public", False)):
        return PUBLIC_SPEC_TENANT_ID
    return DEFAULT_PRIVATE_SPEC_TENANT_ID


def _normalize_spec_tenant_id(value: str | None) -> str:
    token = str(value or "").strip()
    if not token:
        return DEFAULT_PRIVATE_SPEC_TENANT_ID
    return token


def _spec_visible_to_tenant(
    item: dict[str, Any],
    *,
    tenant_id: str | None,
    include_public: bool = True,
) -> bool:
    if tenant_id is None:
        return True
    if include_public and bool(item.get("is_public", False)):
        return True
    return _resolve_item_tenant_id(item) == _normalize_spec_tenant_id(tenant_id)
