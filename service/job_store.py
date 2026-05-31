from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class JobRecord(BaseModel):
    job_id: str
    tenant_id: str = "default"
    status: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    queue_wait_seconds: float | None = None
    run_duration_seconds: float | None = None
    result_sheet_count: int | None = None
    result_issue_count: int | None = None


class JobStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(Path(db_path))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    input_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            _ensure_column_exists(
                conn,
                table_name="jobs",
                column_name="tenant_id",
                column_type="TEXT NOT NULL DEFAULT 'default'",
            )
            _ensure_column_exists(conn, table_name="jobs", column_name="started_at", column_type="TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON jobs(status, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status_created
                ON jobs(tenant_id, status, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_tenant_created
                ON jobs(tenant_id, created_at DESC)
                """
            )
            conn.commit()

    def create_job(self, record: JobRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, tenant_id, status, created_at, updated_at, started_at, completed_at, input_json, result_json, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    _normalize_tenant_id_token(record.tenant_id),
                    record.status,
                    record.created_at,
                    record.updated_at,
                    record.started_at,
                    record.completed_at,
                    json.dumps(record.input),
                    json.dumps(record.result) if record.result is not None else None,
                    record.error,
                ),
            )
            conn.commit()

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        updated_at: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        params: list[object] = [
            status,
            updated_at,
            started_at,
            completed_at,
            json.dumps(result) if result is not None else None,
            error,
            job_id,
        ]
        query = """
                UPDATE jobs
                SET status = ?,
                    updated_at = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = ?,
                    result_json = ?,
                    error = ?
                WHERE job_id = ?
                """
        if tenant_id is not None:
            query += " AND tenant_id = ?"
            params.append(_normalize_tenant_id_token(tenant_id))
        with self._connect() as conn:
            conn.execute(query, tuple(params))
            conn.commit()

    def transition_job_if_current(
        self,
        job_id: str,
        *,
        current_status: str,
        status: str,
        updated_at: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        tenant_id: str | None = None,
    ) -> bool:
        params: list[object] = [
            status,
            updated_at,
            started_at,
            completed_at,
            json.dumps(result) if result is not None else None,
            error,
            job_id,
            current_status,
        ]
        query = """
                UPDATE jobs
                SET status = ?,
                    updated_at = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = ?,
                    result_json = ?,
                    error = ?
                WHERE job_id = ?
                  AND status = ?
                """
        if tenant_id is not None:
            query += " AND tenant_id = ?"
            params.append(_normalize_tenant_id_token(tenant_id))
        with self._connect() as conn:
            cursor = conn.execute(query, tuple(params))
            conn.commit()
            return cursor.rowcount > 0

    def get_job(self, job_id: str, *, tenant_id: str | None = None) -> JobRecord | None:
        with self._connect() as conn:
            if tenant_id is None:
                row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE job_id = ? AND tenant_id = ?",
                    (job_id, _normalize_tenant_id_token(tenant_id)),
                ).fetchone()
        if row is None:
            return None
        return _row_to_job_record(row)

    def list_jobs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        tenant_id: str | None = None,
    ) -> list[JobRecord]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self._connect() as conn:
            if status and tenant_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                      AND tenant_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, _normalize_tenant_id_token(tenant_id), limit, offset),
                ).fetchall()
            elif status:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, limit, offset),
                ).fetchall()
            elif tenant_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE tenant_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (_normalize_tenant_id_token(tenant_id), limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
        return [_row_to_job_record(row) for row in rows]

    def list_recent_jobs(self, *, limit: int = 200, tenant_id: str | None = None) -> list[JobRecord]:
        # Internal analytics path can inspect a wider window than list endpoint pagination.
        limit = max(1, min(limit, 5000))
        with self._connect() as conn:
            if tenant_id is None:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE tenant_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (_normalize_tenant_id_token(tenant_id), limit),
                ).fetchall()
        return [_row_to_job_record(row) for row in rows]

    def count_jobs(self, *, status: str | None = None, tenant_id: str | None = None) -> int:
        with self._connect() as conn:
            if status and tenant_id is not None:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM jobs
                    WHERE status = ?
                      AND tenant_id = ?
                    """,
                    (status, _normalize_tenant_id_token(tenant_id)),
                ).fetchone()
            elif status:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM jobs
                    WHERE status = ?
                    """,
                    (status,),
                ).fetchone()
            elif tenant_id is not None:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM jobs
                    WHERE tenant_id = ?
                    """,
                    (_normalize_tenant_id_token(tenant_id),),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM jobs
                    """
                ).fetchone()
        if row is None:
            return 0
        return int(row["total"])

    def list_jobs_for_prune(
        self,
        *,
        statuses: list[str],
        updated_before: str | None,
        limit: int,
        tenant_id: str | None = None,
    ) -> list[JobRecord]:
        if not statuses:
            return []
        limit = max(1, min(limit, 1000))
        placeholders = ", ".join("?" for _ in statuses)
        params: list[object] = list(statuses)
        query = f"""
            SELECT * FROM jobs
            WHERE status IN ({placeholders})
        """
        if tenant_id is not None:
            query += " AND tenant_id = ?"
            params.append(_normalize_tenant_id_token(tenant_id))
        if updated_before:
            query += " AND updated_at <= ?"
            params.append(updated_before)
        query += " ORDER BY updated_at ASC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_row_to_job_record(row) for row in rows]

    def delete_job(self, job_id: str, *, tenant_id: str | None = None) -> bool:
        with self._connect() as conn:
            if tenant_id is None:
                cursor = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            else:
                cursor = conn.execute(
                    "DELETE FROM jobs WHERE job_id = ? AND tenant_id = ?",
                    (job_id, _normalize_tenant_id_token(tenant_id)),
                )
            conn.commit()
            return cursor.rowcount > 0


def _row_to_job_record(row: sqlite3.Row) -> JobRecord:
    raw_input = row["input_json"]
    raw_result = row["result_json"]
    started_at = row["started_at"] if "started_at" in row.keys() else None
    result_payload = json.loads(raw_result) if raw_result else None
    queue_wait_seconds, run_duration_seconds = _compute_timing_metrics(
        created_at=row["created_at"],
        started_at=started_at,
        completed_at=row["completed_at"],
    )
    result_sheet_count, result_issue_count = _compute_result_counts(result_payload)

    return JobRecord(
        job_id=row["job_id"],
        tenant_id=_normalize_tenant_id_token(row["tenant_id"] if "tenant_id" in row.keys() else "default"),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=started_at,
        completed_at=row["completed_at"],
        input=json.loads(raw_input) if raw_input else {},
        result=result_payload,
        error=row["error"],
        queue_wait_seconds=queue_wait_seconds,
        run_duration_seconds=run_duration_seconds,
        result_sheet_count=result_sheet_count,
        result_issue_count=result_issue_count,
    )


def _ensure_column_exists(
    conn: sqlite3.Connection, *, table_name: str, column_name: str, column_type: str
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {str(row["name"]).lower() for row in rows}
    if column_name.lower() in existing_columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _compute_timing_metrics(
    *, created_at: str, started_at: str | None, completed_at: str | None
) -> tuple[float | None, float | None]:
    created_dt = _parse_iso_datetime(created_at)
    started_dt = _parse_iso_datetime(started_at) if started_at else None
    completed_dt = _parse_iso_datetime(completed_at) if completed_at else None

    queue_wait_seconds: float | None = None
    run_duration_seconds: float | None = None
    if created_dt and started_dt and started_dt >= created_dt:
        queue_wait_seconds = round((started_dt - created_dt).total_seconds(), 3)
    if started_dt and completed_dt and completed_dt >= started_dt:
        run_duration_seconds = round((completed_dt - started_dt).total_seconds(), 3)
    return queue_wait_seconds, run_duration_seconds


def _compute_result_counts(result_payload: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not isinstance(result_payload, dict):
        return None, None

    sheets = result_payload.get("sheets_detected", [])
    issues = result_payload.get("issues_or_ambiguities", [])
    sheet_count = len(sheets) if isinstance(sheets, list) else None
    issue_count = len(issues) if isinstance(issues, list) else None
    return sheet_count, issue_count


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    token = str(value).strip()
    if not token:
        return None
    try:
        return datetime.fromisoformat(token)
    except ValueError:
        return None


def _normalize_tenant_id_token(value: str | None) -> str:
    token = str(value or "").strip()
    return token or "default"
