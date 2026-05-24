from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class JobRecord(BaseModel):
    job_id: str
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None = None
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


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
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    input_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON jobs(status, created_at DESC)
                """
            )
            conn.commit()

    def create_job(self, record: JobRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, created_at, updated_at, completed_at, input_json, result_json, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.status,
                    record.created_at,
                    record.updated_at,
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
        completed_at: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    result_json = ?,
                    error = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    updated_at,
                    completed_at,
                    json.dumps(result) if result is not None else None,
                    error,
                    job_id,
                ),
            )
            conn.commit()

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return _row_to_job_record(row)

    def list_jobs(
        self, *, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[JobRecord]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, limit, offset),
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


def _row_to_job_record(row: sqlite3.Row) -> JobRecord:
    raw_input = row["input_json"]
    raw_result = row["result_json"]
    return JobRecord(
        job_id=row["job_id"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        input=json.loads(raw_input) if raw_input else {},
        result=json.loads(raw_result) if raw_result else None,
        error=row["error"],
    )

