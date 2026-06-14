"""API routes for AI-Estimator — all ``/v1/*`` endpoints.

This module contains every endpoint that was previously defined directly on
the ``app`` object in ``app.py``.  They are now mounted on an ``APIRouter``
with JWT authentication required for all routes (configurable via the
``AI_ESTIMATOR_REQUIRE_AUTH`` environment variable).

The router is included by ``app.py`` with ``prefix=""`` (the ``/v1``
prefix is baked into each route for backward compatibility).
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from typing import Annotated

from service.app_state import (
    ACTIVE_JOB_STATUSES,
    DEFAULT_TENANT_ID,
    LISTABLE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    # Pydantic models
    BenchmarkDashboardResponse,
    BenchmarkGateResponse,
    BenchmarkHistoryResponse,
    BenchmarkTemplateResponse,
    BenchmarkTimelineResponse,
    BenchmarkTrendResponse,
    JobCapacityResponse,
    JobCancelResponse,
    JobCreateResponse,
    JobDeleteResponse,
    JobListResponse,
    JobMetricsGateResponse,
    JobMetricsResponse,
    JobPruneResponse,
    JobReadinessReportResponse,
    JobRerunRecommendationResponse,
    ReviewQueueResponse,
    SheetOverridesTemplateResponse,
    SpecCatalogResponse,
    SpecOrganizationResponse,
    SpecProfileResponse,
    SpecSubmittalSearchResponse,
    SpecUploadResponse,
    TradeCatalogItem,
    TradeCatalogResponse,
    TradeCoverageResponse,
    TradeRecommendationResponse,
    VisualMeasurementsSaveRequest,
    # Helpers
    append_note,
    build_handoff_recommendation,
    cleanup_upload_dirs_for_job,
    allowed_benchmark_roots,
    ensure_benchmark_path_allowed,
    enforce_queued_job_limit,
    format_trade_label,
    get_job_run_semaphore,
    get_job_store,
    get_spec_store,
    get_upload_root,
    maybe_auto_prune_jobs,
    normalize_sheet_overrides_from_input,
    normalize_spec_item,
    parse_bool_env,
    parse_prune_statuses_csv,
    path_is_relative_to,
    queue_rerun_job,
    resolve_benchmark_report_path,
    resolve_benchmark_results_dir,
    resolve_rerun_inputs,
    resolve_spec_profiles_for_request,
    resolve_web_submittal_lookup_enabled,
    run_job,
    safe_file_name,
    save_uploads,
    search_public_product_docs,
    tenant_id_for_request,
    utc_now,
    validate_analysis_scope,
)
from ai_estimator.constants import DEFAULT_CSI_BY_TRADE, TRADE_NAMES
from ai_estimator.benchmark_compare import (
    build_benchmark_dashboard,
    build_benchmark_history,
    build_benchmark_score_timeline,
    build_latest_benchmark_trend_summary,
    evaluate_latest_benchmark_quality_gate,
    compare_latest_benchmark_reports as compare_latest_benchmark_reports_from_dir,
    compare_reports_from_paths,
)
from ai_estimator.pipeline import sanitize_selected_trades
from ai_estimator.spec_intel import build_submittal_queries, parse_csv_tokens
from service.handoff_package import build_job_handoff_zip
from service.job_metrics import build_job_metrics_snapshot, evaluate_job_metrics_gate
from service.job_report import build_job_report_html
from service.job_store import JobRecord
from service.request_parsing import normalize_notes, parse_sheet_overrides_json
from service.spec_store import build_spec_profile_from_file
from service.spec_report import build_spec_compliance_report
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
from service.review_queue import (
    build_benchmark_manifest_template,
    build_review_queue,
    build_sheet_overrides_template,
    build_visual_evidence,
)

# ──────────────────────────────────────────────────────────────────────
# Optional auth dependency
# ──────────────────────────────────────────────────────────────────────


async def _optional_auth() -> None:
    """No-op dependency used when auth is disabled."""
    pass


def _build_auth_dependencies() -> list:
    """Return the list of router-level dependencies based on config.

    When ``AI_ESTIMATOR_REQUIRE_AUTH`` is ``true``, all ``/v1/`` routes
    require a valid JWT via ``get_current_user``.  Otherwise the dependency
    is a no-op so existing API-key users are not broken.
    """
    require = parse_bool_env(os.environ.get("AI_ESTIMATOR_REQUIRE_AUTH", ""))
    if require:
        from service.auth import get_current_user
        from service.db_pg import PgDatabase, get_db
        return [Depends(get_current_user)]
    return [Depends(_optional_auth)]


router = APIRouter(
    prefix="",
    tags=["api"],
    dependencies=_build_auth_dependencies(),
)


# ──────────────────────────────────────────────────────────────────────
# Trade catalog
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/meta/trades", response_model=TradeCatalogResponse)
def get_trade_catalog() -> TradeCatalogResponse:
    return TradeCatalogResponse(
        analysis_modes=["auto", "selected", "all"],
        trades=[
            TradeCatalogItem(
                trade=trade,
                label=format_trade_label(trade),
                csi_codes=list(DEFAULT_CSI_BY_TRADE.get(trade, [])),
            )
            for trade in TRADE_NAMES
        ],
    )


# ──────────────────────────────────────────────────────────────────────
# Spec profiles
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/specs/catalog", response_model=SpecCatalogResponse)
def get_specs_catalog(
    organization: str = "",
    agency: str = "",
    public_only: bool = True,
    project_type: str = "",
    limit: int = 100,
    offset: int = 0,
    request: Request = None,
) -> SpecCatalogResponse:
    tenant_id = tenant_id_for_request(request)
    items, total = get_spec_store().list_specs(
        organization=organization,
        agency=agency,
        public_only=public_only,
        project_type=project_type,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
    )
    return SpecCatalogResponse(
        items=[SpecProfileResponse(**normalize_spec_item(item)) for item in items],
        total_available=total,
        total_returned=len(items),
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


@router.get("/v1/specs/organizations", response_model=SpecOrganizationResponse)
def get_specs_organizations(request: Request = None) -> SpecOrganizationResponse:
    tenant_id = tenant_id_for_request(request)
    return SpecOrganizationResponse(organizations=get_spec_store().list_organizations(tenant_id=tenant_id))


@router.get("/v1/specs/{spec_id}", response_model=SpecProfileResponse)
def get_spec_profile(spec_id: str, request: Request = None) -> SpecProfileResponse:
    tenant_id = tenant_id_for_request(request)
    item = get_spec_store().get_spec(spec_id, tenant_id=tenant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Spec profile not found")
    return SpecProfileResponse(**normalize_spec_item(item))


@router.post("/v1/specs/upload", response_model=SpecUploadResponse)
async def upload_spec_profile(
    spec_file: UploadFile = File(...),
    organization: str = Form(...),
    agency: str = Form(""),
    title: str = Form(""),
    standard_name: str = Form(""),
    project_type: str = Form(""),
    tags_csv: str = Form(""),
    is_public: bool = Form(False),
    notes: str = Form(""),
    request: Request = None,
) -> SpecUploadResponse:
    tenant_id = tenant_id_for_request(request)
    organization_clean = organization.strip()
    if not organization_clean:
        raise HTTPException(status_code=400, detail="organization is required.")
    upload_dir = get_upload_root() / "specs" / str(uuid.uuid4())
    saved = await save_uploads(
        [spec_file],
        upload_dir,
        allowed_suffixes={".pdf", ".txt", ".md", ".csv", ".json"},
    )
    if not saved:
        raise HTTPException(status_code=400, detail="No spec file uploaded.")
    saved_path = saved[0]
    tags = parse_csv_tokens(tags_csv)
    profile = build_spec_profile_from_file(
        file_path=saved_path,
        title=title.strip() or Path(saved_path).stem,
        organization=organization_clean,
        agency=agency.strip() or organization_clean,
        standard_name=standard_name.strip(),
        project_type=project_type.strip(),
        tags=tags,
        notes=notes.strip(),
        is_public=bool(is_public),
        tenant_id=tenant_id,
    )
    stored = get_spec_store().upsert_spec(profile)
    return SpecUploadResponse(item=SpecProfileResponse(**normalize_spec_item(stored)))


@router.get("/v1/specs/submittals/search", response_model=SpecSubmittalSearchResponse)
def search_spec_submittals(
    spec_profile_ids: str = "",
    max_results: int = 10,
    request: Request = None,
) -> SpecSubmittalSearchResponse:
    tenant_id = tenant_id_for_request(request)
    spec_ids = parse_csv_tokens(spec_profile_ids)
    selected_profiles = get_spec_store().get_by_ids(spec_ids, tenant_id=tenant_id)
    queries = build_submittal_queries(spec_profiles=selected_profiles, max_queries=40)
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    web_enabled = resolve_web_submittal_lookup_enabled()

    if not selected_profiles:
        warnings.append("No spec profiles matched the provided spec_profile_ids.")
    if not queries:
        warnings.append("No submittal search queries could be generated from selected specs.")

    if web_enabled and queries:
        for query in queries[: max(1, min(max_results, 25))]:
            items.extend(search_public_product_docs(query=query, limit=2))
    elif queries:
        warnings.append(
            "Web lookup is disabled. Set AI_ESTIMATOR_ENABLE_WEB_SUBMITTALS=true to fetch live links."
        )

    deduped: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for item in items:
        link = str(item.get("url", "")).strip().lower()
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        deduped.append(item)

    return SpecSubmittalSearchResponse(
        query_count=len(queries),
        queries=queries,
        web_lookup_enabled=web_enabled,
        source_profiles=[str(item.get("spec_id", "")).strip() for item in selected_profiles],
        items=deduped[: max(1, min(max_results, 100))],
        warnings=warnings,
    )


# ──────────────────────────────────────────────────────────────────────
# Synchronous analysis
# ──────────────────────────────────────────────────────────────────────


@router.post("/v1/analyze")
async def analyze(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
    sheet_overrides_json: str | None = Form(None),
    spec_profile_ids: str = Form(""),
    spec_organization: str = Form(""),
    include_public_specs: bool = Form(False),
    notes: str | None = Form(None),
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    selected_trade_list = sanitize_selected_trades(selected_trades)
    try:
        validate_analysis_scope(analysis_mode=analysis_mode, selected_trades=selected_trade_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request_id = str(uuid.uuid4())
    request_dir = get_upload_root() / "sync" / request_id
    pdf_paths = await save_uploads(files, request_dir, allowed_suffixes={".pdf"})
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        sheet_overrides = parse_sheet_overrides_json(sheet_overrides_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved_spec_profiles = resolve_spec_profiles_for_request(
        spec_profile_ids_csv=spec_profile_ids,
        spec_organization=spec_organization,
        include_public_specs=include_public_specs,
        tenant_id=tenant_id,
    )
    normalized_notes = normalize_notes(notes)

    try:
        from ai_estimator.pipeline import run_pipeline
        payload = run_pipeline(
            pdf_paths=pdf_paths,
            analysis_mode=analysis_mode,
            selected_trades=selected_trade_list,
            sheet_overrides=sheet_overrides,
            spec_profiles=resolved_spec_profiles,
            notes=normalized_notes,
            validate_schema=True,
        )
        return payload
    finally:
        from service.app_state import should_cleanup_uploads
        if should_cleanup_uploads(mode="sync"):
            shutil.rmtree(request_dir, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────
# Jobs — CRUD
# ──────────────────────────────────────────────────────────────────────


@router.post("/v1/jobs", status_code=202, response_model=JobCreateResponse)
async def create_job(
    files: list[UploadFile] = File(...),
    analysis_mode: str = Form("auto"),
    selected_trades: str = Form(""),
    sheet_overrides_json: str | None = Form(None),
    spec_profile_ids: str = Form(""),
    spec_organization: str = Form(""),
    include_public_specs: bool = Form(False),
    notes: str | None = Form(None),
    request: Request = None,
) -> JobCreateResponse:
    tenant_id = tenant_id_for_request(request)
    selected_trade_list = sanitize_selected_trades(selected_trades)
    try:
        validate_analysis_scope(analysis_mode=analysis_mode, selected_trades=selected_trade_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    maybe_auto_prune_jobs(tenant_id=tenant_id)
    enforce_queued_job_limit(tenant_id=tenant_id)

    job_id = str(uuid.uuid4())
    job_upload_dir = get_upload_root() / "jobs" / job_id
    pdf_paths = await save_uploads(files, job_upload_dir, allowed_suffixes={".pdf"})
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        sheet_overrides = parse_sheet_overrides_json(sheet_overrides_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved_spec_profiles = resolve_spec_profiles_for_request(
        spec_profile_ids_csv=spec_profile_ids,
        spec_organization=spec_organization,
        include_public_specs=include_public_specs,
        tenant_id=tenant_id,
    )
    normalized_notes = normalize_notes(notes)

    now = utc_now()
    record = JobRecord(
        job_id=job_id,
        tenant_id=tenant_id,
        status="queued",
        created_at=now,
        updated_at=now,
        input={
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trade_list,
            "sheet_overrides": sheet_overrides or [],
            "spec_profile_ids": [str(item.get("spec_id", "")).strip() for item in resolved_spec_profiles],
            "spec_organization": spec_organization.strip(),
            "include_public_specs": bool(include_public_specs),
            "notes": normalized_notes,
            "tenant_id": tenant_id,
            "uploaded_files": [
                {
                    "file_name": Path(path).name,
                    "path": str(path),
                }
                for path in pdf_paths
            ],
        },
    )
    get_job_store().create_job(record)

    from threading import Thread
    thread = Thread(
        target=run_job,
        kwargs={
            "job_id": job_id,
            "pdf_paths": pdf_paths,
            "analysis_mode": analysis_mode,
            "selected_trades": selected_trade_list,
            "sheet_overrides": sheet_overrides,
            "spec_profiles": resolved_spec_profiles,
            "notes": normalized_notes,
            "upload_dir": str(job_upload_dir),
            "tenant_id": tenant_id,
        },
        daemon=True,
    )
    thread.start()
    return JobCreateResponse(job_id=job_id, status="queued")


@router.post("/v1/jobs/{job_id}/rerun", status_code=202, response_model=JobCreateResponse)
async def rerun_job(
    job_id: str,
    analysis_mode: str | None = Form(None),
    selected_trades: str | None = Form(None),
    sheet_overrides_json: str | None = Form(None),
    spec_profile_ids: str | None = Form(None),
    spec_organization: str | None = Form(None),
    include_public_specs: bool | None = Form(None),
    notes: str | None = Form(None),
    request: Request = None,
) -> JobCreateResponse:
    tenant_id = tenant_id_for_request(request)
    maybe_auto_prune_jobs(tenant_id=tenant_id)
    enforce_queued_job_limit(tenant_id=tenant_id)
    source_record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not source_record:
        raise HTTPException(status_code=404, detail="Job not found")

    source_input = source_record.input if isinstance(source_record.input, dict) else {}
    try:
        (
            resolved_mode,
            resolved_trades,
            resolved_overrides,
            resolved_spec_profiles,
            resolved_spec_organization,
            resolved_include_public_specs,
            resolved_notes,
        ) = resolve_rerun_inputs(
            source_input=source_input,
            tenant_id=tenant_id,
            analysis_mode=analysis_mode,
            selected_trades=selected_trades,
            sheet_overrides_json=sheet_overrides_json,
            spec_profile_ids=spec_profile_ids,
            spec_organization=spec_organization,
            include_public_specs=include_public_specs,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from service.app_state import resolve_uploaded_pdf_paths
    pdf_paths, missing_paths = resolve_uploaded_pdf_paths(source_input)
    if not pdf_paths:
        raise HTTPException(
            status_code=409,
            detail=(
                "No reusable uploaded files were found for this job. "
                "Submit a new job with files, or disable async upload cleanup."
            ),
        )
    if missing_paths:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Some uploaded files from the source job are missing. "
                    "Disable async upload cleanup or submit a new job with files."
                ),
                "missing_paths": missing_paths[:20],
            },
        )

    rerun_job_id = queue_rerun_job(
        source_job_id=job_id,
        tenant_id=tenant_id,
        pdf_paths=pdf_paths,
        analysis_mode=resolved_mode,
        selected_trades=resolved_trades,
        sheet_overrides=resolved_overrides,
        spec_profiles=resolved_spec_profiles,
        notes=resolved_notes,
        extra_input={
            "spec_profile_ids": [
                str(item.get("spec_id", "")).strip() for item in resolved_spec_profiles
            ],
            "spec_organization": resolved_spec_organization,
            "include_public_specs": resolved_include_public_specs,
        },
    )
    return JobCreateResponse(job_id=rerun_job_id, status="queued")


@router.post("/v1/jobs/{job_id}/cancel", response_model=JobCancelResponse)
def cancel_job(
    job_id: str,
    request: Request = None,
) -> JobCancelResponse:
    tenant_id = tenant_id_for_request(request)
    store = get_job_store()
    record = store.get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = str(record.status).strip().lower()
    if current_status == "canceled":
        return JobCancelResponse(
            job_id=job_id,
            status="canceled",
            previous_status="canceled",
            message="Job is already canceled.",
        )
    if current_status in {"completed", "failed"}:
        raise HTTPException(
            status_code=409,
            detail=f"Job is already terminal ({current_status}) and cannot be canceled.",
        )

    now = utc_now()
    if current_status == "queued":
        updated = store.transition_job_if_current(
            job_id,
            current_status="queued",
            status="canceled",
            updated_at=now,
            completed_at=now,
            error="Job canceled by user before execution.",
            tenant_id=tenant_id,
        )
        message = "Queued job canceled."
    elif current_status == "running":
        updated = store.transition_job_if_current(
            job_id,
            current_status="running",
            status="canceled",
            updated_at=now,
            completed_at=now,
            error=(
                "Job canceled by user while running. "
                "Worker completion updates will be ignored."
            ),
            tenant_id=tenant_id,
        )
        message = "Running job marked canceled."
    else:
        raise HTTPException(
            status_code=409,
            detail=f"Job status '{current_status}' does not support cancellation.",
        )

    if updated:
        return JobCancelResponse(
            job_id=job_id,
            status="canceled",
            previous_status=current_status,
            message=message,
        )

    latest = store.get_job(job_id, tenant_id=tenant_id)
    latest_status = str(latest.status).strip().lower() if latest else "unknown"
    if latest_status == "canceled":
        return JobCancelResponse(
            job_id=job_id,
            status="canceled",
            previous_status=current_status,
            message="Job is already canceled.",
        )
    if latest_status in {"completed", "failed"}:
        raise HTTPException(
            status_code=409,
            detail=f"Job reached terminal state '{latest_status}' before cancellation applied.",
        )
    raise HTTPException(
        status_code=409,
        detail=f"Job status changed to '{latest_status}' before cancellation could be applied.",
    )


@router.delete("/v1/jobs/{job_id}", response_model=JobDeleteResponse)
def delete_job(
    job_id: str,
    cleanup_uploads: bool = False,
    request: Request = None,
) -> JobDeleteResponse:
    tenant_id = tenant_id_for_request(request)
    store = get_job_store()
    record = store.get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = str(record.status).strip().lower()
    if current_status in ACTIVE_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete active job with status '{current_status}'. "
                "Cancel or wait for completion first."
            ),
        )

    removed_dirs: list[str] = []
    skipped_dirs: list[str] = []
    if cleanup_uploads:
        removed_dirs, skipped_dirs = cleanup_upload_dirs_for_job(record)

    deleted = store.delete_job(job_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Job changed before deletion could be applied.",
        )

    return JobDeleteResponse(
        job_id=job_id,
        deleted=True,
        previous_status=current_status,
        removed_upload_dirs=removed_dirs,
        skipped_upload_dirs=skipped_dirs,
    )


# ──────────────────────────────────────────────────────────────────────
# Jobs — prune (exposed as a public helper for app_state)
# ──────────────────────────────────────────────────────────────────────


@router.post("/v1/jobs/prune", response_model=JobPruneResponse)
def prune_jobs(
    statuses: str = "completed,failed,canceled",
    older_than_hours: int | None = None,
    limit: int = 100,
    dry_run: bool = True,
    cleanup_uploads: bool = False,
    tenant_id: str | None = None,
    request: Request = None,
) -> JobPruneResponse:
    return do_prune_jobs(
        statuses=statuses,
        older_than_hours=older_than_hours,
        limit=limit,
        dry_run=dry_run,
        cleanup_uploads=cleanup_uploads,
        tenant_id=tenant_id,
        request=request,
    )


def do_prune_jobs(
    statuses: str = "completed,failed,canceled",
    older_than_hours: int | None = None,
    limit: int = 100,
    dry_run: bool = True,
    cleanup_uploads: bool = False,
    tenant_id: str | None = None,
    request: Request | None = None,
) -> JobPruneResponse:
    """Prune implementation – also called by ``app_state.maybe_auto_prune_jobs``."""
    resolved_tenant_id = tenant_id_for_request(request, explicit_tenant_id=tenant_id)
    status_tokens = parse_prune_statuses_csv(statuses)
    if older_than_hours is not None and older_than_hours < 1:
        raise HTTPException(status_code=400, detail="older_than_hours must be at least 1 when provided.")

    cutoff_updated_at: str | None = None
    if older_than_hours is not None:
        cutoff_updated_at = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()

    limit_applied = max(1, min(limit, 1000))
    store = get_job_store()
    candidates = store.list_jobs_for_prune(
        statuses=status_tokens,
        updated_before=cutoff_updated_at,
        limit=limit_applied,
        tenant_id=resolved_tenant_id,
    )
    eligible_job_ids = [record.job_id for record in candidates]
    if dry_run:
        return JobPruneResponse(
            dry_run=True,
            statuses=status_tokens,
            older_than_hours=older_than_hours,
            cutoff_updated_at=cutoff_updated_at,
            limit=limit_applied,
            total_eligible=len(eligible_job_ids),
            total_deleted=0,
            eligible_job_ids=eligible_job_ids,
            deleted_job_ids=[],
            skipped_jobs=[],
            removed_upload_dirs=[],
            skipped_upload_dirs=[],
        )

    deleted_job_ids: list[str] = []
    skipped_jobs: list[dict[str, str]] = []
    removed_upload_dirs: list[str] = []
    skipped_upload_dirs: list[str] = []
    removed_seen: set[str] = set()
    skipped_seen: set[str] = set()

    for candidate in candidates:
        latest = store.get_job(candidate.job_id, tenant_id=resolved_tenant_id)
        if not latest:
            skipped_jobs.append({"job_id": candidate.job_id, "reason": "Job not found during prune."})
            continue
        latest_status = str(latest.status).strip().lower()
        if latest_status not in TERMINAL_JOB_STATUSES:
            skipped_jobs.append(
                {
                    "job_id": latest.job_id,
                    "reason": f"Status changed to active state '{latest_status}'.",
                }
            )
            continue

        if cleanup_uploads:
            removed_batch, skipped_batch = cleanup_upload_dirs_for_job(latest)
            for path in removed_batch:
                key = path.lower()
                if key in removed_seen:
                    continue
                removed_seen.add(key)
                removed_upload_dirs.append(path)
            for path in skipped_batch:
                key = path.lower()
                if key in skipped_seen:
                    continue
                skipped_seen.add(key)
                skipped_upload_dirs.append(path)

        deleted = store.delete_job(latest.job_id, tenant_id=resolved_tenant_id)
        if deleted:
            deleted_job_ids.append(latest.job_id)
        else:
            skipped_jobs.append({"job_id": latest.job_id, "reason": "Delete operation was not applied."})

    return JobPruneResponse(
        dry_run=False,
        statuses=status_tokens,
        older_than_hours=older_than_hours,
        cutoff_updated_at=cutoff_updated_at,
        limit=limit_applied,
        total_eligible=len(eligible_job_ids),
        total_deleted=len(deleted_job_ids),
        eligible_job_ids=eligible_job_ids,
        deleted_job_ids=deleted_job_ids,
        skipped_jobs=skipped_jobs,
        removed_upload_dirs=removed_upload_dirs,
        skipped_upload_dirs=skipped_upload_dirs,
    )


# ──────────────────────────────────────────────────────────────────────
# Jobs — rerun-recommended
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/v1/jobs/{job_id}/rerun-recommended",
    status_code=202,
    response_model=JobRerunRecommendationResponse,
)
def rerun_job_with_recommendation(
    job_id: str,
    request: Request = None,
) -> JobRerunRecommendationResponse:
    tenant_id = tenant_id_for_request(request)
    maybe_auto_prune_jobs(tenant_id=tenant_id)
    enforce_queued_job_limit(tenant_id=tenant_id)
    source_record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not source_record:
        raise HTTPException(status_code=404, detail="Job not found")

    source_input = source_record.input if isinstance(source_record.input, dict) else {}
    from service.app_state import resolve_uploaded_pdf_paths
    pdf_paths, missing_paths = resolve_uploaded_pdf_paths(source_input)
    if not pdf_paths:
        raise HTTPException(
            status_code=409,
            detail=(
                "No reusable uploaded files were found for this job. "
                "Submit a new job with files, or disable async upload cleanup."
            ),
        )
    if missing_paths:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Some uploaded files from the source job are missing. "
                    "Disable async upload cleanup or submit a new job with files."
                ),
                "missing_paths": missing_paths[:20],
            },
        )

    recommendation = build_trade_recommendation(
        job_id=job_id,
        result=source_record.result if isinstance(source_record.result, dict) else None,
    )
    recommended_mode = str(recommendation.get("recommended_mode", "all")).strip().lower()
    if recommended_mode not in {"selected", "all"}:
        recommended_mode = "all"
    recommended_trades_raw = recommendation.get("recommended_trades", [])
    recommended_trades = (
        [str(trade).strip() for trade in recommended_trades_raw if str(trade).strip()]
        if isinstance(recommended_trades_raw, list)
        else []
    )
    if recommended_mode != "selected":
        recommended_trades = []

    resolved_notes = normalize_notes(
        append_note(
            source_notes=source_input.get("notes") if isinstance(source_input.get("notes"), str) else None,
            marker=(
                "Auto rerun using trade recommendation: "
                f"mode={recommended_mode}, confidence={recommendation.get('confidence')}."
            ),
        )
    )
    resolved_overrides = normalize_sheet_overrides_from_input(source_input.get("sheet_overrides"))
    resolved_spec_profiles = resolve_spec_profiles_for_request(
        spec_profile_ids_csv=",".join(
            str(token).strip() for token in source_input.get("spec_profile_ids", []) if str(token).strip()
        ),
        spec_organization=str(source_input.get("spec_organization", "")).strip(),
        include_public_specs=bool(source_input.get("include_public_specs", False)),
        tenant_id=tenant_id,
    )

    rerun_job_id = queue_rerun_job(
        source_job_id=job_id,
        tenant_id=tenant_id,
        pdf_paths=pdf_paths,
        analysis_mode=recommended_mode,
        selected_trades=recommended_trades,
        sheet_overrides=resolved_overrides,
        spec_profiles=resolved_spec_profiles,
        notes=resolved_notes,
        extra_input={
            "trade_recommendation": {
                "recommended_mode": recommended_mode,
                "recommended_trades": recommended_trades,
                "confidence": recommendation.get("confidence"),
            },
            "spec_profile_ids": [str(item.get("spec_id", "")).strip() for item in resolved_spec_profiles],
            "spec_organization": str(source_input.get("spec_organization", "")).strip(),
            "include_public_specs": bool(source_input.get("include_public_specs", False)),
        },
    )
    confidence_raw = recommendation.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
    return JobRerunRecommendationResponse(
        job_id=rerun_job_id,
        status="queued",
        source_job_id=job_id,
        recommended_mode=recommended_mode,
        recommended_trades=recommended_trades,
        recommendation_confidence=confidence,
    )


# ──────────────────────────────────────────────────────────────────────
# Jobs — metrics & capacity
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/jobs/metrics", response_model=JobMetricsResponse)
def get_job_metrics(
    window: int = 200,
    request: Request = None,
) -> JobMetricsResponse:
    tenant_id = tenant_id_for_request(request)
    window_applied = max(1, min(window, 5000))
    records = get_job_store().list_recent_jobs(limit=window_applied, tenant_id=tenant_id)
    payload = build_job_metrics_snapshot(
        records,
        window_requested=window,
        window_applied=window_applied,
        generated_at=utc_now(),
    )
    return JobMetricsResponse(**payload)


@router.get("/v1/jobs/metrics/gate", response_model=JobMetricsGateResponse)
def get_job_metrics_gate(
    window: int = 200,
    max_failure_rate: float | None = None,
    max_active_jobs: int | None = None,
    max_missing_scale_rate: float | None = None,
    max_unmapped_sheet_rate: float | None = None,
    min_jobs_per_hour_24h: float | None = None,
    request: Request = None,
) -> JobMetricsGateResponse:
    tenant_id = tenant_id_for_request(request)
    window_applied = max(1, min(window, 5000))
    records = get_job_store().list_recent_jobs(limit=window_applied, tenant_id=tenant_id)
    snapshot = build_job_metrics_snapshot(
        records,
        window_requested=window,
        window_applied=window_applied,
        generated_at=utc_now(),
    )
    payload = evaluate_job_metrics_gate(
        snapshot,
        max_failure_rate=max_failure_rate,
        max_active_jobs=max_active_jobs,
        max_missing_scale_rate=max_missing_scale_rate,
        max_unmapped_sheet_rate=max_unmapped_sheet_rate,
        min_jobs_per_hour_24h=min_jobs_per_hour_24h,
    )
    return JobMetricsGateResponse(**payload)


@router.get("/v1/jobs/capacity", response_model=JobCapacityResponse)
def get_job_capacity(
    request: Request = None,
) -> JobCapacityResponse:
    tenant_id = tenant_id_for_request(request)
    store = get_job_store()
    from service.app_state import resolve_job_worker_limit, resolve_max_queued_jobs
    worker_limit = resolve_job_worker_limit()
    running_jobs = store.count_jobs(status="running", tenant_id=tenant_id)
    queued_jobs = store.count_jobs(status="queued", tenant_id=tenant_id)
    max_queued_jobs = resolve_max_queued_jobs()
    queue_capacity_remaining = (
        max(0, max_queued_jobs - queued_jobs) if max_queued_jobs is not None else None
    )
    return JobCapacityResponse(
        worker_limit=worker_limit,
        running_jobs=running_jobs,
        queued_jobs=queued_jobs,
        running_slots_available=max(0, worker_limit - running_jobs),
        max_queued_jobs=max_queued_jobs,
        queue_capacity_remaining=queue_capacity_remaining,
    )


# ──────────────────────────────────────────────────────────────────────
# Jobs — single job operations
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return record.model_dump()


@router.get("/v1/jobs/{job_id}/review-queue", response_model=ReviewQueueResponse)
def get_job_review_queue(
    job_id: str,
    low_confidence_threshold: float = 0.75,
    include_only_flagged: bool = True,
    request: Request = None,
) -> ReviewQueueResponse:
    if low_confidence_threshold < 0 or low_confidence_threshold > 1:
        raise HTTPException(status_code=400, detail="low_confidence_threshold must be between 0 and 1.")
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_review_queue(
        job_id=job_id,
        result=record.result,
        low_confidence_threshold=low_confidence_threshold,
        include_only_flagged=include_only_flagged,
    )
    return ReviewQueueResponse(**payload)


@router.get("/v1/jobs/{job_id}/sheet-overrides-template", response_model=SheetOverridesTemplateResponse)
def get_sheet_overrides_template(
    job_id: str,
    include_all: bool = False,
    request: Request = None,
) -> SheetOverridesTemplateResponse:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_sheet_overrides_template(
        job_id=job_id,
        result=record.result,
        include_all=include_all,
    )
    return SheetOverridesTemplateResponse(**payload)


@router.get("/v1/jobs/{job_id}/visual-evidence")
def get_job_visual_evidence(
    job_id: str,
    limit: int = 250,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_visual_evidence(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
        limit=limit,
    )


@router.get("/v1/jobs/{job_id}/takeoff.csv")
def get_job_takeoff_csv(
    job_id: str,
    request: Request = None,
) -> Response:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    csv_text = build_takeoff_csv(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="takeoff-{safe_file_name(job_id)}.csv"'
        },
    )


@router.get("/v1/jobs/{job_id}/takeoff-line-items")
def get_job_takeoff_line_items(
    job_id: str,
    trade: str = "",
    quantity_name: str = "",
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_takeoff_line_items_payload(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
        trade=trade,
        quantity_name=quantity_name,
    )


@router.get("/v1/jobs/{job_id}/report.html", response_class=HTMLResponse)
def get_job_report_html(
    job_id: str,
    tenant_id: str | None = None,
    request: Request = None,
) -> HTMLResponse:
    resolved_tenant_id = tenant_id_for_request(request, explicit_tenant_id=tenant_id)
    record = get_job_store().get_job(job_id, tenant_id=resolved_tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    html = build_job_report_html(
        job_id=record.job_id,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        input_payload=record.input if isinstance(record.input, dict) else None,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return HTMLResponse(content=html)


@router.get("/v1/jobs/{job_id}/spec-compliance")
def get_job_spec_compliance(
    job_id: str,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_spec_compliance_report(
        job_id=record.job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )


@router.get("/v1/jobs/{job_id}/handoff.zip")
def get_job_handoff_package(
    job_id: str,
    request: Request = None,
) -> Response:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_job_handoff_zip(
        job_id=record.job_id,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        input_payload=record.input if isinstance(record.input, dict) else {},
        result=record.result if isinstance(record.result, dict) else None,
    )
    safe_id = safe_file_name(job_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="handoff-{safe_id}.zip"'
        },
    )


@router.get("/v1/jobs/{job_id}/visual-evidence.svg")
def get_job_visual_evidence_svg(
    job_id: str,
    sheet_id: str = "",
    source_page_index: int | None = None,
    limit: int = 500,
    request: Request = None,
) -> Response:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    svg = build_visual_evidence_svg(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
        sheet_id=sheet_id or None,
        source_page_index=source_page_index,
        limit=limit,
    )
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/v1/jobs/{job_id}/visual-review", response_class=HTMLResponse)
def get_job_visual_review_page(
    job_id: str,
    sheet_id: str = "",
    source_page_index: int | None = None,
    tenant_id: str | None = None,
    limit: int = 500,
    request: Request = None,
) -> str:
    resolved_tenant_id = tenant_id_for_request(request, explicit_tenant_id=tenant_id)
    record = get_job_store().get_job(job_id, tenant_id=resolved_tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_visual_measurement_page(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
        sheet_id=sheet_id or None,
        source_page_index=source_page_index,
        tenant_id=resolved_tenant_id,
        limit=limit,
    )


@router.get("/v1/jobs/{job_id}/visual-measurements")
def get_job_visual_measurements(
    job_id: str,
    sheet_id: str,
    source_page_index: int | None = None,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    if not isinstance(record.result, dict):
        raise HTTPException(status_code=409, detail="Job does not have a completed result.")
    measurements = list_visual_measurements(
        result=record.result,
        sheet_id=sheet_id,
        source_page_index=source_page_index,
    )
    return {
        "job_id": job_id,
        "sheet_id": sheet_id,
        "source_page_index": source_page_index,
        "measurement_count": len(measurements),
        "measurements": measurements,
    }


@router.put("/v1/jobs/{job_id}/visual-measurements")
def save_job_visual_measurements(
    job_id: str,
    payload: VisualMeasurementsSaveRequest,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    store = get_job_store()
    record = store.get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    if not isinstance(record.result, dict):
        raise HTTPException(status_code=409, detail="Job does not have a completed result.")
    try:
        updated_result, save_payload = save_visual_measurements_to_result(
            result=record.result,
            sheet_id=payload.sheet_id,
            source_page_index=payload.source_page_index,
            measurements=payload.measurements,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc).isoformat()
    store.update_job(
        job_id,
        status=record.status,
        updated_at=now,
        started_at=record.started_at,
        completed_at=record.completed_at,
        result=updated_result,
        error=record.error,
        tenant_id=tenant_id,
    )
    return {
        "job_id": job_id,
        **save_payload,
    }


# ──────────────────────────────────────────────────────────────────────
# Jobs — scale calibration
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/jobs/{job_id}/scale-calibration/preview")
def get_job_scale_calibration_preview(
    job_id: str,
    sheet_id: str,
    measured_pdf_units: float,
    known_length_ft: float,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        return build_scale_calibration_preview(
            job_id=job_id,
            result=record.result if isinstance(record.result, dict) else None,
            sheet_id=sheet_id,
            measured_pdf_units=measured_pdf_units,
            known_length_ft=known_length_ft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/jobs/{job_id}/scale-calibration/apply")
def apply_job_scale_calibration(
    job_id: str,
    sheet_id: str,
    measured_pdf_units: float,
    known_length_ft: float,
    request: Request = None,
) -> dict[str, Any]:
    tenant_id = tenant_id_for_request(request)
    store = get_job_store()
    record = store.get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    if not isinstance(record.result, dict):
        raise HTTPException(status_code=409, detail="Job does not have a completed result to calibrate.")
    try:
        updated_result, payload = apply_scale_calibration_to_result(
            result=record.result,
            sheet_id=sheet_id,
            measured_pdf_units=measured_pdf_units,
            known_length_ft=known_length_ft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc).isoformat()
    store.update_job(
        job_id,
        status=record.status,
        updated_at=now,
        started_at=record.started_at,
        completed_at=record.completed_at,
        result=updated_result,
        error=record.error,
        tenant_id=tenant_id,
    )
    return {
        "job_id": job_id,
        **payload,
    }


# ──────────────────────────────────────────────────────────────────────
# Jobs — trade recommendation & coverage
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/jobs/{job_id}/trade-recommendation", response_model=TradeRecommendationResponse)
def get_trade_recommendation(
    job_id: str,
    request: Request = None,
) -> TradeRecommendationResponse:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_trade_recommendation(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return TradeRecommendationResponse(**payload)


@router.get("/v1/jobs/{job_id}/trade-coverage", response_model=TradeCoverageResponse)
def get_trade_coverage(
    job_id: str,
    request: Request = None,
) -> TradeCoverageResponse:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_trade_coverage_report(
        job_id=job_id,
        result=record.result if isinstance(record.result, dict) else None,
    )
    return TradeCoverageResponse(**payload)


@router.get("/v1/jobs/{job_id}/readiness-report", response_model=JobReadinessReportResponse)
def get_job_readiness_report(
    job_id: str,
    request: Request = None,
) -> JobReadinessReportResponse:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    result_payload = record.result if isinstance(record.result, dict) else None
    review_queue = build_review_queue(
        job_id=job_id,
        result=result_payload,
        low_confidence_threshold=0.75,
        include_only_flagged=True,
    )
    trade_rec = build_trade_recommendation(job_id=job_id, result=result_payload)
    trade_cov = build_trade_coverage_report(job_id=job_id, result=result_payload)

    recent_records = get_job_store().list_recent_jobs(limit=500, tenant_id=tenant_id)
    snapshot = build_job_metrics_snapshot(
        recent_records,
        window_requested=500,
        window_applied=500,
        generated_at=utc_now(),
    )
    ops_gate = evaluate_job_metrics_gate(
        snapshot,
        max_failure_rate=0.2,
        max_active_jobs=25,
        max_missing_scale_rate=0.4,
        max_unmapped_sheet_rate=0.25,
        min_jobs_per_hour_24h=0.05,
    )
    handoff = build_handoff_recommendation(
        review_queue_summary=review_queue.get("summary", {}),
        trade_recommendation=trade_rec,
        trade_coverage=trade_cov,
        ops_gate=ops_gate,
    )

    return JobReadinessReportResponse(
        job_id=job_id,
        generated_at=utc_now(),
        review_queue_summary=review_queue.get("summary", {}),
        trade_recommendation=trade_rec,
        trade_coverage=trade_cov,
        ops_gate=ops_gate,
        handoff_recommendation=handoff,
    )


@router.get("/v1/jobs/{job_id}/benchmark-template", response_model=BenchmarkTemplateResponse)
def get_benchmark_template(
    job_id: str,
    include_unmapped: bool = False,
    case_id: str | None = None,
    request: Request = None,
) -> BenchmarkTemplateResponse:
    tenant_id = tenant_id_for_request(request)
    record = get_job_store().get_job(job_id, tenant_id=tenant_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = build_benchmark_manifest_template(
        job_id=job_id,
        result=record.result,
        job_input=record.input if isinstance(record.input, dict) else {},
        include_unmapped=include_unmapped,
        case_id=case_id,
    )
    return BenchmarkTemplateResponse(**payload)


# ──────────────────────────────────────────────────────────────────────
# Benchmark reports
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/benchmark-reports/compare")
def compare_benchmark_reports_endpoint(
    baseline_path: str,
    candidate_path: str,
) -> dict[str, Any]:
    baseline = resolve_benchmark_report_path(baseline_path, label="Baseline")
    candidate = resolve_benchmark_report_path(candidate_path, label="Candidate")
    if not baseline.exists():
        raise HTTPException(status_code=404, detail=f"Baseline report not found: {baseline}")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Candidate report not found: {candidate}")

    try:
        return compare_reports_from_paths(baseline, candidate)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/benchmark-reports/compare-latest")
def compare_latest_benchmark_reports_endpoint(
    results_dir: str = "",
) -> dict[str, Any]:
    target_dir = resolve_benchmark_results_dir(results_dir)

    try:
        return compare_latest_benchmark_reports_from_dir(target_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/benchmark-reports/history", response_model=BenchmarkHistoryResponse)
def get_benchmark_reports_history(
    results_dir: str = "",
    limit: int = 50,
    offset: int = 0,
) -> BenchmarkHistoryResponse:
    target_dir = resolve_benchmark_results_dir(results_dir)

    payload = build_benchmark_history(results_dir=target_dir, limit=limit, offset=offset)
    return BenchmarkHistoryResponse(**payload)


@router.get("/v1/benchmark-reports/trend", response_model=BenchmarkTrendResponse)
def get_benchmark_reports_trend(
    results_dir: str = "",
) -> BenchmarkTrendResponse:
    target_dir = resolve_benchmark_results_dir(results_dir)

    try:
        payload = build_latest_benchmark_trend_summary(target_dir)
        return BenchmarkTrendResponse(**payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/benchmark-reports/gate", response_model=BenchmarkGateResponse)
def get_benchmark_reports_gate(
    results_dir: str = "",
    min_candidate_score: float | None = None,
    max_negative_delta: float | None = None,
    require_non_regression: bool = True,
    require_improvement: bool = False,
) -> BenchmarkGateResponse:
    target_dir = resolve_benchmark_results_dir(results_dir)

    try:
        payload = evaluate_latest_benchmark_quality_gate(
            target_dir,
            min_candidate_score=min_candidate_score,
            max_negative_delta=max_negative_delta,
            require_non_regression=require_non_regression,
            require_improvement=require_improvement,
        )
        return BenchmarkGateResponse(**payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/benchmark-reports/timeline", response_model=BenchmarkTimelineResponse)
def get_benchmark_reports_timeline(
    results_dir: str = "",
    limit: int = 30,
    offset: int = 0,
) -> BenchmarkTimelineResponse:
    target_dir = resolve_benchmark_results_dir(results_dir)

    payload = build_benchmark_score_timeline(results_dir=target_dir, limit=limit, offset=offset)
    return BenchmarkTimelineResponse(**payload)


@router.get("/v1/benchmark-reports/dashboard", response_model=BenchmarkDashboardResponse)
def get_benchmark_reports_dashboard(
    results_dir: str = "",
    history_limit: int = 20,
    history_offset: int = 0,
    timeline_limit: int = 30,
    timeline_offset: int = 0,
    gate_min_candidate_score: float | None = None,
    gate_max_negative_delta: float | None = None,
    gate_require_non_regression: bool = True,
    gate_require_improvement: bool = False,
) -> BenchmarkDashboardResponse:
    target_dir = resolve_benchmark_results_dir(results_dir)

    payload = build_benchmark_dashboard(
        results_dir=target_dir,
        history_limit=history_limit,
        history_offset=history_offset,
        timeline_limit=timeline_limit,
        timeline_offset=timeline_offset,
        gate_min_candidate_score=gate_min_candidate_score,
        gate_max_negative_delta=gate_max_negative_delta,
        gate_require_non_regression=gate_require_non_regression,
        gate_require_improvement=gate_require_improvement,
    )
    return BenchmarkDashboardResponse(**payload)


# ──────────────────────────────────────────────────────────────────────
# Jobs — list
# ──────────────────────────────────────────────────────────────────────


@router.get("/v1/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    request: Request = None,
) -> JobListResponse:
    if status and status not in LISTABLE_JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status filter must be one of: queued, running, completed, failed, canceled",
        )
    tenant_id = tenant_id_for_request(request)
    items = get_job_store().list_jobs(
        limit=limit,
        offset=offset,
        status=status,
        tenant_id=tenant_id,
    )
    return JobListResponse(
        items=items,
        total_returned=len(items),
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )
