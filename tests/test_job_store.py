from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from service.job_store import JobRecord, JobStore


def test_job_store_create_update_get_and_list(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    store = JobStore(str(db_path))

    record = JobRecord(
        job_id="job-1",
        status="queued",
        created_at="2026-05-24T00:00:00+00:00",
        updated_at="2026-05-24T00:00:00+00:00",
        input={"analysis_mode": "auto", "selected_trades": []},
    )
    store.create_job(record)

    stored = store.get_job("job-1")
    assert stored is not None
    assert stored.status == "queued"
    assert stored.result is None
    assert stored.started_at is None
    assert stored.queue_wait_seconds is None
    assert stored.run_duration_seconds is None
    assert stored.result_sheet_count is None
    assert stored.result_issue_count is None

    store.update_job(
        "job-1",
        status="running",
        updated_at="2026-05-24T00:00:03+00:00",
        started_at="2026-05-24T00:00:03+00:00",
        completed_at=None,
        result=None,
        error=None,
    )
    store.update_job(
        "job-1",
        status="completed",
        updated_at="2026-05-24T00:01:00+00:00",
        completed_at="2026-05-24T00:01:00+00:00",
        result={
            "ok": True,
            "sheets_detected": [{"sheet_id": "A101"}, {"sheet_id": "A102"}],
            "issues_or_ambiguities": [{"message": "missing scale"}],
        },
        error=None,
    )
    updated = store.get_job("job-1")
    assert updated is not None
    assert updated.status == "completed"
    assert updated.result is not None
    assert updated.result["ok"] is True
    assert updated.started_at == "2026-05-24T00:00:03+00:00"
    assert updated.completed_at == "2026-05-24T00:01:00+00:00"
    assert updated.queue_wait_seconds == 3.0
    assert updated.run_duration_seconds == 57.0
    assert updated.result_sheet_count == 2
    assert updated.result_issue_count == 1

    listed = store.list_jobs(limit=10, offset=0)
    assert len(listed) == 1
    assert listed[0].job_id == "job-1"


def test_job_store_migrates_legacy_db_without_started_at(tmp_path: Path):
    db_path = tmp_path / "jobs_legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE jobs (
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
        INSERT INTO jobs (
            job_id, status, created_at, updated_at, completed_at, input_json, result_json, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-1",
            "queued",
            "2026-05-24T00:00:00+00:00",
            "2026-05-24T00:00:00+00:00",
            None,
            json.dumps({"analysis_mode": "auto", "selected_trades": []}),
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()

    store = JobStore(str(db_path))
    record = store.get_job("legacy-1")
    assert record is not None
    assert record.started_at is None

    store.update_job(
        "legacy-1",
        status="running",
        updated_at="2026-05-24T00:00:10+00:00",
        started_at="2026-05-24T00:00:10+00:00",
    )
    updated = store.get_job("legacy-1")
    assert updated is not None
    assert updated.started_at == "2026-05-24T00:00:10+00:00"
