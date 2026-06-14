"""Shared application state and helper functions for AI-Estimator.

This module holds the module-level singletons (job store, spec store, upload
root, etc.) and the private helper functions that are used by both
``app.py`` and ``routes_api.py``.  Keeping them here avoids circular imports
between the two modules.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import BoundedSemaphore, Lock, Thread
from typing import Any

from fastapi import HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ai_estimator.constants import DEFAULT_CSI_BY_TRADE, TRADE_NAMES
from ai_estimator.pipeline import run_pipeline, sanitize_selected_trades
from ai_estimator.spec_intel import build_submittal_queries, parse_csv_tokens
from service.job_store import JobRecord, JobStore
from service.request_parsing import normalize_notes, parse_sheet_overrides_json
from service.spec_store import SpecStore, build_spec_profile_from_file
from service.review_queue import (
    build_benchmark_manifest_template,
    build_review_queue,
    build_sheet_overrides_template,
    build_visual_evidence,
)
from service.takeoff_export import build_takeoff_csv
from service.takeoff_line_items import build_takeoff_line_items_payload
from service.trade_coverage import build_trade_coverage_report
from service.trade_recommendation import build_trade_recommendation
from service.visual_review import (
    apply_scale_calibration_to_result,
    build_scale_calibration_preview,
    build_visual_evidence_svg,
    build_visual_measurement_page,
    list_visual_measurements,
    save_visual_measurements_to_result,
)
from service.logging_config import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

TERMINAL_JOB_STATUSES = {"completed", "failed", "canceled"}
ACTIVE_JOB_STATUSES = {"queued", "running"}
LISTABLE_JOB_STATUSES = ACTIVE_JOB_STATUSES | TERMINAL_JOB_STATUSES
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
DEFAULT_TENANT_ID = "default"
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")

# ──────────────────────────────────────────────────────────────────────
# Pydantic response models
# ──────────────────────────────────────────────────────────────────────


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobCancelResponse(BaseModel):
    job_id: str
    status: str
    previous_status: str
    message: str


class JobDeleteResponse(BaseModel):
    job_id: str
    deleted: bool
    previous_status: str
    removed_upload_dirs: list[str]
    skipped_upload_dirs: list[str]


class JobPruneResponse(BaseModel):
    dry_run: bool
    statuses: list[str]
    older_than_hours: int | None
    cutoff_updated_at: str | None
    limit: int
    total_eligible: int
    total_deleted: int
    eligible_job_ids: list[str]
    deleted_job_ids: list[str]
    skipped_jobs: list[dict[str, str]]
    removed_upload_dirs: list[str]
    skipped_upload_dirs: list[str]


class VisualMeasurementsSaveRequest(BaseModel):
    sheet_id: str
    source_page_index: int | None = None
    measurements: list[dict[str, Any]] = Field(default_factory=list)


class TradeCatalogItem(BaseModel):
    trade: str
    label: str
    csi_codes: list[str]


class TradeCatalogResponse(BaseModel):
    analysis_modes: list[str]
    trades: list[TradeCatalogItem]


class SpecProfileResponse(BaseModel):
    spec_id: str
    tenant_id: str = "public"
    title: str
    organization: str
    agency: str
    standard_name: str
    project_type: str
    tags: list[str]
    is_public: bool
    source_file_name: str
    source_file_path: str
    notes: str
    detected_standard_refs: list[str]
    detected_trade_hints: list[str]
    text_excerpt: str
    created_at: str
    updated_at: str


class SpecCatalogResponse(BaseModel):
    items: list[SpecProfileResponse]
    total_available: int
    total_returned: int
    limit: int
    offset: int


class SpecOrganizationResponse(BaseModel):
    organizations: list[str]


class SpecUploadResponse(BaseModel):
    item: SpecProfileResponse


class SpecSubmittalSearchResponse(BaseModel):
    query_count: int
    queries: list[str]
    web_lookup_enabled: bool
    source_profiles: list[str]
    items: list[dict[str, Any]]
    warnings: list[str]


class JobListResponse(BaseModel):
    items: list[JobRecord]
    total_returned: int
    limit: int
    offset: int


class JobMetricsResponse(BaseModel):
    generated_at: str
    window_requested: int
    window_applied: int
    jobs_considered: int
    status_counts: dict[str, int]
    active_jobs: int
    terminal_jobs: int
    failure_rate: float | None
    throughput_last_24h: dict[str, float | int | None]
    queue_wait_seconds: dict[str, float | int | None]
    run_duration_seconds: dict[str, float | int | None]
    result_sheet_count: dict[str, float | int | None]
    result_issue_count: dict[str, float | int | None]
    quality: dict[str, float | int | None]


class JobMetricsGateResponse(BaseModel):
    passed: bool
    thresholds: dict[str, float | int | None]
    actual: dict[str, float | int | None]
    failures: list[dict[str, Any]]
    snapshot: dict[str, Any]


class JobCapacityResponse(BaseModel):
    worker_limit: int
    running_jobs: int
    queued_jobs: int
    running_slots_available: int
    max_queued_jobs: int | None
    queue_capacity_remaining: int | None


class TradeRecommendationResponse(BaseModel):
    job_id: str
    requested_mode: str
    requested_trades: list[str]
    detected_trades: list[str]
    recommended_mode: str
    recommended_trades: list[str]
    confidence: float
    needs_user_review: bool
    decision_rationale: list[str]
    trade_scores: list[dict[str, Any]]


class TradeCoverageResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    needs_review_trades: list[str]
    trades: list[dict[str, Any]]


class JobReadinessReportResponse(BaseModel):
    job_id: str
    generated_at: str
    review_queue_summary: dict[str, Any]
    trade_recommendation: dict[str, Any]
    trade_coverage: dict[str, Any]
    ops_gate: dict[str, Any]
    handoff_recommendation: dict[str, Any]


class JobRerunRecommendationResponse(JobCreateResponse):
    source_job_id: str
    recommended_mode: str
    recommended_trades: list[str]
    recommendation_confidence: float | None


class ReviewQueueResponse(BaseModel):
    job_id: str
    low_confidence_threshold: float
    summary: dict[str, Any]
    items: list[dict[str, Any]]


class SheetOverridesTemplateResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    items: list[dict[str, Any]]


class BenchmarkTemplateResponse(BaseModel):
    job_id: str
    summary: dict[str, Any]
    manifest: dict[str, Any]


class BenchmarkHistoryResponse(BaseModel):
    results_dir: str
    total_available: int
    total_returned: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class BenchmarkTrendResponse(BaseModel):
    results_dir: str
    total_available: int
    trend: str | None
    overall_score_delta: float | None
    comparison_mode: str
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    metric_count: int


class BenchmarkTimelineResponse(BaseModel):
    results_dir: str
    total_available: int
    total_returned: int
    limit: int
    offset: int
    points: list[dict[str, Any]]


class BenchmarkGateResponse(BaseModel):
    results_dir: str
    total_available: int
    passed: bool
    thresholds: dict[str, Any]
    actual: dict[str, Any]
    failures: list[dict[str, Any]]


class BenchmarkDashboardResponse(BaseModel):
    results_dir: str
    total_available: int
    history: dict[str, Any]
    timeline: dict[str, Any]
    trend: dict[str, Any] | None
    gate: dict[str, Any] | None
    warnings: list[str]


# ──────────────────────────────────────────────────────────────────────
# Module-level singletons
# ──────────────────────────────────────────────────────────────────────

job_store: JobStore | None = None
spec_store: SpecStore | None = None
upload_root: Path | None = None
resource_lock = Lock()
_job_run_semaphore: BoundedSemaphore | None = None
_job_run_semaphore_limit: int | None = None


# ──────────────────────────────────────────────────────────────────────
# Singleton getters
# ──────────────────────────────────────────────────────────────────────


def get_job_store() -> JobStore:
    global job_store
    if job_store is None:
        with resource_lock:
            if job_store is None:
                job_store = JobStore(resolve_db_path())
    return job_store


def get_spec_store() -> SpecStore:
    global spec_store
    if spec_store is None:
        with resource_lock:
            if spec_store is None:
                spec_store = SpecStore(resolve_spec_store_path())
    return spec_store


def get_upload_root() -> Path:
    global upload_root
    if upload_root is None:
        with resource_lock:
            if upload_root is None:
                upload_root = Path(resolve_upload_root())
                upload_root.mkdir(parents=True, exist_ok=True)
    return upload_root


def get_job_run_semaphore() -> BoundedSemaphore:
    global _job_run_semaphore, _job_run_semaphore_limit
    with resource_lock:
        limit = resolve_job_worker_limit()
        if _job_run_semaphore is None or _job_run_semaphore_limit != limit:
            _job_run_semaphore = BoundedSemaphore(limit)
            _job_run_semaphore_limit = limit
    return _job_run_semaphore


# ──────────────────────────────────────────────────────────────────────
# Utility / resolver helpers
# ──────────────────────────────────────────────────────────────────────


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_db_path() -> str:
    override = os.environ.get("AI_ESTIMATOR_DB_PATH", "").strip()
    if override:
        return override
    return str(Path.cwd() / ".ai_estimator" / "jobs.db")


def resolve_upload_root() -> str:
    override = os.environ.get("AI_ESTIMATOR_UPLOAD_DIR", "").strip()
    if override:
        return override
    return str(Path.cwd() / ".ai_estimator" / "uploads")


def resolve_spec_store_path() -> str:
    override = os.environ.get("AI_ESTIMATOR_SPEC_STORE_PATH", "").strip()
    if override:
        return override
    return str(Path.cwd() / ".ai_estimator" / "spec_store.json")


def resolve_positive_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def resolve_max_upload_files() -> int:
    return resolve_positive_int_env(
        "AI_ESTIMATOR_MAX_UPLOAD_FILES",
        default=20,
        minimum=1,
        maximum=500,
    )


def resolve_max_upload_file_bytes() -> int:
    mb = resolve_positive_int_env(
        "AI_ESTIMATOR_MAX_UPLOAD_FILE_MB",
        default=200,
        minimum=1,
        maximum=10_000,
    )
    return mb * 1024 * 1024


def resolve_max_upload_total_bytes() -> int:
    mb = resolve_positive_int_env(
        "AI_ESTIMATOR_MAX_UPLOAD_TOTAL_MB",
        default=1_000,
        minimum=1,
        maximum=50_000,
    )
    return mb * 1024 * 1024


def resolve_max_queued_jobs() -> int | None:
    raw = os.environ.get("AI_ESTIMATOR_MAX_QUEUED_JOBS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return min(value, 100000)


def resolve_auto_prune_on_submit() -> bool:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_ON_SUBMIT", "")
    return parse_bool_env(raw)


def resolve_auto_prune_older_than_hours() -> int | None:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 1:
        return None
    return min(value, 24 * 365 * 20)


def resolve_auto_prune_limit() -> int:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_LIMIT", "").strip()
    if not raw:
        return 200
    try:
        value = int(raw)
    except ValueError:
        return 200
    return max(1, min(value, 1000))


def resolve_auto_prune_cleanup_uploads() -> bool:
    raw = os.environ.get("AI_ESTIMATOR_PRUNE_CLEANUP_UPLOADS", "")
    return parse_bool_env(raw)


def resolve_job_worker_limit() -> int:
    default_limit = 4
    raw = os.environ.get("AI_ESTIMATOR_JOB_WORKERS", "").strip()
    if not raw:
        return default_limit
    try:
        value = int(raw)
    except ValueError:
        return default_limit
    return max(1, min(32, value))


def should_cleanup_uploads(mode: str) -> bool:
    if mode not in {"sync", "async"}:
        raise ValueError("mode must be 'sync' or 'async'.")

    specific_var = (
        "AI_ESTIMATOR_CLEANUP_SYNC_UPLOADS"
        if mode == "sync"
        else "AI_ESTIMATOR_CLEANUP_ASYNC_UPLOADS"
    )
    specific_raw = os.environ.get(specific_var)
    if specific_raw is not None:
        return parse_bool_env(specific_raw)

    global_raw = os.environ.get("AI_ESTIMATOR_CLEANUP_UPLOADS")
    if global_raw is not None:
        return parse_bool_env(global_raw)

    # Default: clean up sync uploads, retain async uploads for reruns/audit.
    return mode == "sync"


def parse_bool_env(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_uploaded_pdf_paths(source_input: dict[str, Any]) -> tuple[list[str], list[str]]:
    uploaded_files = source_input.get("uploaded_files")
    if not isinstance(uploaded_files, list):
        return [], []

    paths: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for item in uploaded_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        if Path(path).exists():
            paths.append(path)
        else:
            missing.append(path)
    return paths, missing


def cleanup_upload_dirs_for_job(record: JobRecord) -> tuple[list[str], list[str]]:
    job_input = record.input if isinstance(record.input, dict) else {}
    uploaded_files = job_input.get("uploaded_files")
    if not isinstance(uploaded_files, list):
        return [], []

    root = get_upload_root().resolve()
    candidate_dirs: list[Path] = []
    seen: set[str] = set()
    for item in uploaded_files:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            continue
        try:
            parent = Path(raw_path).expanduser().resolve(strict=False).parent
        except OSError:
            continue
        key = str(parent).lower()
        if key in seen:
            continue
        seen.add(key)
        candidate_dirs.append(parent)

    removed: list[str] = []
    skipped: list[str] = []
    for candidate in candidate_dirs:
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root):
            skipped.append(str(resolved))
            continue
        if not resolved.exists():
            continue
        shutil.rmtree(resolved, ignore_errors=True)
        removed.append(str(resolved))
    return removed, skipped


def queue_rerun_job(
    *,
    source_job_id: str,
    tenant_id: str,
    pdf_paths: list[str],
    analysis_mode: str,
    selected_trades: list[str],
    sheet_overrides: list[dict[str, Any]] | None,
    spec_profiles: list[dict[str, Any]] | None,
    notes: str | None,
    extra_input: dict[str, Any],
) -> str:
    rerun_job_id = str(uuid.uuid4())
    now = utc_now()
    payload_input: dict[str, Any] = {
        "analysis_mode": analysis_mode,
        "selected_trades": selected_trades,
        "sheet_overrides": sheet_overrides or [],
        "spec_profile_ids": [str(item.get("spec_id", "")).strip() for item in (spec_profiles or [])],
        "notes": notes,
        "tenant_id": tenant_id,
        "uploaded_files": [
            {
                "file_name": Path(path).name,
                "path": str(path),
            }
            for path in pdf_paths
        ],
        "rerun_of_job_id": source_job_id,
    }
    payload_input.update(extra_input)

    record = JobRecord(
        job_id=rerun_job_id,
        tenant_id=tenant_id,
        status="queued",
        created_at=now,
        updated_at=now,
        input=payload_input,
    )
    get_job_store().create_job(record)

    thread = Thread(
        target=run_job,
        kwargs={
            "job_id": rerun_job_id,
            "pdf_paths": pdf_paths,
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trades,
            "sheet_overrides": sheet_overrides,
            "spec_profiles": spec_profiles,
            "notes": notes,
            "upload_dir": None,
            "tenant_id": tenant_id,
        },
        daemon=True,
    )
    thread.start()
    return rerun_job_id


def append_note(*, source_notes: str | None, marker: str) -> str:
    base = source_notes.strip() if isinstance(source_notes, str) else ""
    marker_clean = marker.strip()
    if not base:
        return marker_clean
    if marker_clean.lower() in base.lower():
        return base
    return f"{base}\n{marker_clean}"


def is_api_key_authorized(*, expected: str, provided: str) -> bool:
    return bool(expected.strip()) and expected.strip() == provided.strip()


def resolve_default_tenant_id() -> str:
    raw = os.environ.get("AI_ESTIMATOR_DEFAULT_TENANT_ID", DEFAULT_TENANT_ID)
    token = str(raw).strip() or DEFAULT_TENANT_ID
    try:
        return normalize_tenant_id(token)
    except ValueError:
        return DEFAULT_TENANT_ID


def normalize_tenant_id(raw: str) -> str:
    token = str(raw).strip()
    if not token:
        raise ValueError("Tenant ID cannot be empty.")
    if not TENANT_ID_PATTERN.match(token):
        raise ValueError(
            "Invalid tenant ID. Use 1-80 characters: letters, numbers, '.', '-', or '_'."
        )
    return token


def tenant_id_for_request(
    request: Request | None,
    *,
    explicit_tenant_id: str | None = None,
) -> str:
    tenant_candidate = str(explicit_tenant_id or "").strip()
    if not tenant_candidate and request is not None:
        tenant_candidate = str(request.headers.get("x-tenant-id", "")).strip()

    if not tenant_candidate:
        require_header = parse_bool_env(os.environ.get("AI_ESTIMATOR_REQUIRE_TENANT_ID", ""))
        if request is not None and require_header and explicit_tenant_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Tenant ID is required. Provide header 'x-tenant-id' or configure "
                    "AI_ESTIMATOR_DEFAULT_TENANT_ID."
                ),
            )
        return resolve_default_tenant_id()

    try:
        return normalize_tenant_id(tenant_candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_handoff_recommendation(
    *,
    review_queue_summary: dict[str, Any],
    trade_recommendation: dict[str, Any],
    trade_coverage: dict[str, Any],
    ops_gate: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    flagged_sheets = int(review_queue_summary.get("flagged_sheets", 0))
    if flagged_sheets > 0:
        reasons.append(f"{flagged_sheets} sheet(s) remain flagged in review queue.")

    needs_review_count = 0
    coverage_summary = trade_coverage.get("summary", {})
    if isinstance(coverage_summary, dict):
        raw_needs_review = coverage_summary.get("needs_review_count", 0)
        if isinstance(raw_needs_review, int):
            needs_review_count = raw_needs_review
    if needs_review_count > 0:
        reasons.append(f"{needs_review_count} trade(s) need coverage review.")

    if not bool(ops_gate.get("passed", False)):
        failure_count = len(ops_gate.get("failures", [])) if isinstance(ops_gate.get("failures"), list) else "n/a"
        reasons.append(f"Operations gate failed ({failure_count} failure(s)).")

    if trade_recommendation.get("needs_user_review") is True:
        reasons.append("Trade recommendation indicates elevated uncertainty.")

    if reasons:
        status = "blocked"
    elif trade_recommendation.get("recommended_mode") == "all":
        status = "review_required"
        reasons.append("Recommended mode is 'all'; verify scope before handoff.")
    else:
        status = "ready"
        reasons.append("No blocking findings in queue, coverage, or ops gate.")

    return {
        "status": status,
        "reasons": reasons,
    }


def resolve_rerun_inputs(
    *,
    source_input: dict[str, Any],
    tenant_id: str,
    analysis_mode: str | None,
    selected_trades: str | None,
    sheet_overrides_json: str | None,
    spec_profile_ids: str | None,
    spec_organization: str | None,
    include_public_specs: bool | None,
    notes: str | None,
) -> tuple[
    str,
    list[str],
    list[dict[str, Any]] | None,
    list[dict[str, Any]],
    str,
    bool,
    str | None,
]:
    if analysis_mode is None:
        resolved_mode = str(source_input.get("analysis_mode", "auto")).strip() or "auto"
    else:
        resolved_mode = analysis_mode.strip()

    if selected_trades is None:
        raw_trades = source_input.get("selected_trades", [])
        if not isinstance(raw_trades, list):
            raw_trades = []
        csv = ",".join(str(item).strip() for item in raw_trades if str(item).strip())
        resolved_trades = sanitize_selected_trades(csv)
    else:
        resolved_trades = sanitize_selected_trades(selected_trades)
    validate_analysis_scope(analysis_mode=resolved_mode, selected_trades=resolved_trades)

    if sheet_overrides_json is None:
        resolved_overrides = normalize_sheet_overrides_from_input(source_input.get("sheet_overrides"))
    else:
        resolved_overrides = parse_sheet_overrides_json(sheet_overrides_json)

    if spec_profile_ids is None:
        raw_spec_ids = source_input.get("spec_profile_ids", [])
        if isinstance(raw_spec_ids, list):
            resolved_spec_profile_ids_csv = ",".join(
                str(item).strip() for item in raw_spec_ids if str(item).strip()
            )
        else:
            resolved_spec_profile_ids_csv = ""
    else:
        resolved_spec_profile_ids_csv = spec_profile_ids

    if spec_organization is None:
        resolved_spec_organization = str(source_input.get("spec_organization", "")).strip()
    else:
        resolved_spec_organization = spec_organization.strip()

    if include_public_specs is None:
        resolved_include_public_specs = bool(source_input.get("include_public_specs", False))
    else:
        resolved_include_public_specs = bool(include_public_specs)

    resolved_spec_profiles = resolve_spec_profiles_for_request(
        spec_profile_ids_csv=resolved_spec_profile_ids_csv,
        spec_organization=resolved_spec_organization,
        include_public_specs=resolved_include_public_specs,
        tenant_id=tenant_id,
    )

    if notes is None:
        source_notes = source_input.get("notes")
        resolved_notes = normalize_notes(source_notes if isinstance(source_notes, str) else None)
    else:
        resolved_notes = normalize_notes(notes)

    return (
        resolved_mode,
        resolved_trades,
        resolved_overrides,
        resolved_spec_profiles,
        resolved_spec_organization,
        resolved_include_public_specs,
        resolved_notes,
    )


def validate_analysis_scope(*, analysis_mode: str, selected_trades: list[str]) -> None:
    if analysis_mode not in {"auto", "selected", "all"}:
        raise ValueError("analysis_mode must be auto, selected, or all")
    if analysis_mode == "selected" and not selected_trades:
        raise ValueError(
            "selected_trades must include at least one valid trade when analysis_mode is selected"
        )


def format_trade_label(trade: str) -> str:
    token_map = {
        "hvac": "HVAC",
        "it": "IT",
    }
    words = []
    for token in trade.split("_"):
        lower = token.lower()
        words.append(token_map.get(lower, token.capitalize()))
    return " ".join(words)


def parse_prune_statuses_csv(raw: str) -> list[str]:
    token_map: list[str] = []
    seen: set[str] = set()
    for token in str(raw).split(","):
        normalized = token.strip().lower()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        token_map.append(normalized)
    if not token_map:
        token_map = sorted(TERMINAL_JOB_STATUSES)

    invalid = [token for token in token_map if token not in LISTABLE_JOB_STATUSES]
    if invalid:
        allowed = ", ".join(sorted(LISTABLE_JOB_STATUSES))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prune statuses: {', '.join(invalid)}. Allowed: {allowed}.",
        )

    active = [token for token in token_map if token in ACTIVE_JOB_STATUSES]
    if active:
        raise HTTPException(
            status_code=400,
            detail=(
                "Prune supports terminal statuses only. "
                f"Remove active statuses: {', '.join(active)}."
            ),
        )
    return token_map


def normalize_sheet_overrides_from_input(raw: object) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {
            "sheet_id": str(item.get("sheet_id", "")).strip(),
            "title": str(item.get("title", "")).strip(),
        }
        source_page_index = item.get("source_page_index")
        if isinstance(source_page_index, int) and source_page_index >= 1:
            row["source_page_index"] = source_page_index
        elif isinstance(source_page_index, str):
            token = source_page_index.strip()
            if token.isdigit():
                value = int(token)
                if value >= 1:
                    row["source_page_index"] = value
        normalized.append(row)
    return normalized


def safe_file_name(name: str) -> str:
    allowed = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in name)
    normalized = allowed.strip("_")
    return normalized[:80] or "drawing"


def normalize_spec_item(raw: dict[str, Any]) -> dict[str, Any]:
    tenant_id = str(raw.get("tenant_id", "")).strip()
    if not tenant_id:
        tenant_id = "public" if bool(raw.get("is_public", False)) else DEFAULT_TENANT_ID
    return {
        "spec_id": str(raw.get("spec_id", "")).strip(),
        "tenant_id": tenant_id,
        "title": str(raw.get("title", "")).strip(),
        "organization": str(raw.get("organization", "")).strip(),
        "agency": str(raw.get("agency", "")).strip(),
        "standard_name": str(raw.get("standard_name", "")).strip(),
        "project_type": str(raw.get("project_type", "")).strip(),
        "tags": [str(item).strip() for item in raw.get("tags", []) if str(item).strip()]
        if isinstance(raw.get("tags"), list)
        else [],
        "is_public": bool(raw.get("is_public", False)),
        "source_file_name": str(raw.get("source_file_name", "")).strip(),
        "source_file_path": str(raw.get("source_file_path", "")).strip(),
        "notes": str(raw.get("notes", "")).strip(),
        "detected_standard_refs": [
            str(item).strip().upper()
            for item in raw.get("detected_standard_refs", [])
            if str(item).strip()
        ]
        if isinstance(raw.get("detected_standard_refs"), list)
        else [],
        "detected_trade_hints": [
            str(item).strip()
            for item in raw.get("detected_trade_hints", [])
            if str(item).strip()
        ]
        if isinstance(raw.get("detected_trade_hints"), list)
        else [],
        "text_excerpt": str(raw.get("text_excerpt", "")).strip(),
        "created_at": str(raw.get("created_at", "")).strip() or utc_now(),
        "updated_at": str(raw.get("updated_at", "")).strip() or utc_now(),
    }


def resolve_spec_profiles_for_request(
    *,
    spec_profile_ids_csv: str | None,
    spec_organization: str | None,
    include_public_specs: bool,
    tenant_id: str,
) -> list[dict[str, Any]]:
    s_store = get_spec_store()
    spec_ids = parse_csv_tokens(spec_profile_ids_csv)
    selected = s_store.get_by_ids(spec_ids, tenant_id=tenant_id)

    if include_public_specs:
        public_matches, _total = s_store.list_specs(
            organization=(spec_organization or "").strip(),
            public_only=True,
            tenant_id=tenant_id,
            limit=1000,
            offset=0,
        )
        selected_map: dict[str, dict[str, Any]] = {
            str(item.get("spec_id", "")).strip(): item for item in selected
        }
        for item in public_matches:
            spec_id = str(item.get("spec_id", "")).strip()
            if spec_id and spec_id not in selected_map:
                selected_map[spec_id] = item
        selected = list(selected_map.values())

    return [normalize_spec_item(item) for item in selected]


def resolve_web_submittal_lookup_enabled() -> bool:
    return parse_bool_env(os.environ.get("AI_ESTIMATOR_ENABLE_WEB_SUBMITTALS", ""))


def search_public_product_docs(*, query: str, limit: int) -> list[dict[str, str]]:
    import requests

    search_url = "https://duckduckgo.com/html/"
    results: list[dict[str, str]] = []
    try:
        response = requests.get(
            search_url,
            params={"q": query},
            timeout=20,
            headers={"User-Agent": "AI-Estimator/0.1"},
        )
        response.raise_for_status()
    except Exception:
        return results

    html = response.text
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        href = str(match.group("href")).strip()
        title = re.sub(r"<[^>]+>", "", str(match.group("title"))).strip()
        if not href:
            continue
        results.append({"query": query, "title": title, "url": href})
        if len(results) >= max(1, min(limit, 20)):
            break
    return results


# ──────────────────────────────────────────────────────────────────────
# Benchmark helpers
# ──────────────────────────────────────────────────────────────────────


def resolve_benchmark_results_dir(results_dir: str) -> Path:
    if str(results_dir).strip():
        target_dir = Path(str(results_dir).strip()).expanduser().resolve()
    else:
        target_dir = Path.cwd().joinpath("benchmarks", "results").resolve()
    ensure_benchmark_path_allowed(target_dir)
    return target_dir


def resolve_benchmark_report_path(report_path: str, *, label: str) -> Path:
    target = Path(str(report_path).strip()).expanduser().resolve()
    ensure_benchmark_path_allowed(target)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"{label} report not found: {target}")
    return target


def ensure_benchmark_path_allowed(target: Path) -> None:
    if parse_bool_env(os.environ.get("AI_ESTIMATOR_ALLOW_ARBITRARY_BENCHMARK_PATHS", "")):
        return
    roots = allowed_benchmark_roots()
    if any(path_is_relative_to(target, root) for root in roots):
        return
    allowed = ", ".join(str(root) for root in roots)
    raise HTTPException(
        status_code=400,
        detail=(
            f"Benchmark path is outside allowed results directories: {target}. "
            f"Allowed roots: {allowed}. Set AI_ESTIMATOR_ALLOW_ARBITRARY_BENCHMARK_PATHS=true "
            "for local development only."
        ),
    )


def allowed_benchmark_roots() -> list[Path]:
    roots = [Path.cwd().joinpath("benchmarks", "results")]
    configured = os.environ.get("AI_ESTIMATOR_BENCHMARK_RESULTS_DIRS", "").strip()
    if configured:
        roots.extend(Path(item).expanduser() for item in configured.split(os.pathsep) if item.strip())
    return [root.resolve() for root in roots]


def path_is_relative_to(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────────────────────────────
# Upload helpers
# ──────────────────────────────────────────────────────────────────────


async def save_uploads(
    files: list[UploadFile],
    target_dir: Path,
    *,
    allowed_suffixes: set[str] | None = None,
) -> list[str]:
    max_files = resolve_max_upload_files()
    max_file_bytes = resolve_max_upload_file_bytes()
    max_total_bytes = resolve_max_upload_total_bytes()
    if len(files) > max_files:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload rejected: {len(files)} files exceeds limit of {max_files}. "
                "Reduce the number of files or increase AI_ESTIMATOR_MAX_UPLOAD_FILES."
            ),
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_paths: list[str] = []
    total_written = 0
    for index, upload in enumerate(files):
        suffix = Path(upload.filename or "drawing.pdf").suffix or ".pdf"
        suffix = suffix.lower()
        display_name = upload.filename or f"upload_{index + 1}{suffix}"
        if allowed_suffixes is not None:
            normalized_allowed = {item.lower() for item in allowed_suffixes}
            if suffix not in normalized_allowed:
                allowed_text = ", ".join(sorted(normalized_allowed))
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Upload rejected: '{display_name}' has unsupported "
                        f"file type '{suffix}'. Allowed file types: {allowed_text}."
                    ),
                )
        clean_name = safe_file_name(Path(upload.filename or f"drawing_{index + 1}.pdf").stem)
        target_path = target_dir / f"{index + 1:03d}_{clean_name}{suffix}"
        file_written = 0
        try:
            with target_path.open("wb") as handle:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE_BYTES)
                    if not chunk:
                        break
                    chunk_size = len(chunk)
                    file_written += chunk_size
                    total_written += chunk_size
                    if file_written > max_file_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"Upload rejected: '{upload.filename or target_path.name}' is too large "
                                f"({file_written // (1024 * 1024)} MB). Limit is "
                                f"{max_file_bytes // (1024 * 1024)} MB per file "
                                "(AI_ESTIMATOR_MAX_UPLOAD_FILE_MB)."
                            ),
                        )
                    if total_written > max_total_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                "Upload rejected: total upload size exceeded limit "
                                f"of {max_total_bytes // (1024 * 1024)} MB "
                                "(AI_ESTIMATOR_MAX_UPLOAD_TOTAL_MB)."
                            ),
                        )
                    handle.write(chunk)
            if file_written <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Upload rejected: '{upload.filename or target_path.name}' is empty.",
                )
            pdf_paths.append(str(target_path))
        except HTTPException:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Upload failed while saving '{upload.filename or target_path.name}': {exc}",
            ) from exc
    return pdf_paths


# ──────────────────────────────────────────────────────────────────────
# Job execution
# ──────────────────────────────────────────────────────────────────────


def run_job(
    job_id: str,
    pdf_paths: list[str],
    analysis_mode: str,
    selected_trades: list[str],
    sheet_overrides: list[dict[str, object]] | None,
    spec_profiles: list[dict[str, object]] | None,
    notes: str | None,
    upload_dir: str | None,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> None:
    run_semaphore = get_job_run_semaphore()
    run_semaphore.acquire()
    try:
        store = get_job_store()
        started_at = utc_now()
        claimed = store.transition_job_if_current(
            job_id,
            current_status="queued",
            status="running",
            updated_at=started_at,
            started_at=started_at,
            tenant_id=tenant_id,
        )
        if not claimed:
            return
        try:
            result = run_pipeline(
                pdf_paths=pdf_paths,
                analysis_mode=analysis_mode,
                selected_trades=selected_trades,
                sheet_overrides=sheet_overrides,
                spec_profiles=spec_profiles,
                notes=notes,
                validate_schema=True,
            )
            now = utc_now()
            store.transition_job_if_current(
                job_id,
                current_status="running",
                status="completed",
                updated_at=now,
                completed_at=now,
                result=result,
                error=None,
                tenant_id=tenant_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            now = utc_now()
            store.transition_job_if_current(
                job_id,
                current_status="running",
                status="failed",
                updated_at=now,
                completed_at=now,
                result=None,
                error=str(exc),
                tenant_id=tenant_id,
            )
    finally:
        run_semaphore.release()
        if upload_dir and should_cleanup_uploads(mode="async"):
            shutil.rmtree(upload_dir, ignore_errors=True)


def maybe_auto_prune_jobs(*, tenant_id: str | None = None) -> dict[str, Any] | None:
    if not resolve_auto_prune_on_submit():
        return None
    try:
        prune_kwargs: dict[str, Any] = {
            "statuses": "completed,failed,canceled",
            "older_than_hours": resolve_auto_prune_older_than_hours(),
            "limit": resolve_auto_prune_limit(),
            "dry_run": False,
            "cleanup_uploads": resolve_auto_prune_cleanup_uploads(),
        }
        if tenant_id is not None:
            prune_kwargs["tenant_id"] = tenant_id
        from service.routes_api import do_prune_jobs
        payload = do_prune_jobs(**prune_kwargs)
        return payload.model_dump()
    except Exception:
        # Auto-prune should never block the primary job submission path.
        return None


def enforce_queued_job_limit(*, tenant_id: str | None = None) -> None:
    max_queued = resolve_max_queued_jobs()
    if max_queued is None:
        return
    queued = get_job_store().count_jobs(status="queued", tenant_id=tenant_id)
    if queued >= max_queued:
        raise HTTPException(
            status_code=429,
            detail=(
                "Job queue is at capacity. "
                f"queued={queued}, max_queued={max_queued}. "
                "Retry later or increase AI_ESTIMATOR_MAX_QUEUED_JOBS."
            ),
        )
