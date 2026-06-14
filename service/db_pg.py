"""Async PostgreSQL database module for AI-Estimator SaaS.

Provides:
- Connection pooling via ``asyncpg.create_pool``
- Auto-creation of all required tables on startup
- Parameterized queries only (no string interpolation)
- A ``get_db()`` FastAPI dependency for injection

Usage::

    from service.db_pg import PgDatabase, get_db

    # At application startup:
    db = PgDatabase(database_url)
    await db.init()

    # FastAPI dependency:
    async def my_route(db: PgDatabase = Depends(get_db)):
        ...
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import asyncpg
from fastapi import Depends

from service.config import settings


# ──────────────────────────────────────────────────────────────────────
# Pydantic-style record models (kept lightweight, no pydantic import
# to avoid circular dependency issues with the service layer).
# ──────────────────────────────────────────────────────────────────────


class UserRecord:
    __slots__ = (
        "id", "email", "hashed_password", "full_name", "company_name",
        "role", "plan", "stripe_customer_id", "created_at", "updated_at",
    )

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        email: str,
        hashed_password: str,
        full_name: str = "",
        company_name: str = "",
        role: str = "estimator",
        plan: str = "free",
        stripe_customer_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = id or uuid.uuid4()
        self.email = email
        self.hashed_password = hashed_password
        self.full_name = full_name
        self.company_name = company_name
        self.role = role
        self.plan = plan
        self.stripe_customer_id = stripe_customer_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)


class JobRecordPg:
    """Mirrors the existing ``JobRecord`` but with ``user_id`` (UUID FK)
    instead of ``tenant_id`` (TEXT)."""

    __slots__ = (
        "job_id", "user_id", "status", "created_at", "updated_at",
        "started_at", "completed_at", "input", "result", "error",
    )

    def __init__(
        self,
        *,
        job_id: str,
        user_id: uuid.UUID,
        status: str,
        created_at: datetime,
        updated_at: datetime,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        input: dict[str, Any],
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.job_id = job_id
        self.user_id = user_id
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.started_at = started_at
        self.completed_at = completed_at
        self.input = input
        self.result = result
        self.error = error


class SubscriptionRecord:
    __slots__ = (
        "id", "user_id", "stripe_subscription_id", "stripe_price_id",
        "status", "current_period_start", "current_period_end", "created_at",
    )

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        user_id: uuid.UUID,
        stripe_subscription_id: str,
        stripe_price_id: str,
        status: str = "active",
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id or uuid.uuid4()
        self.user_id = user_id
        self.stripe_subscription_id = stripe_subscription_id
        self.stripe_price_id = stripe_price_id
        self.status = status
        self.current_period_start = current_period_start or datetime.now(timezone.utc)
        self.current_period_end = current_period_end
        self.created_at = created_at or datetime.now(timezone.utc)


class ApiKeyRecord:
    __slots__ = ("id", "user_id", "key_hash", "name", "last_used_at", "created_at")

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        user_id: uuid.UUID,
        key_hash: str,
        name: str = "default",
        last_used_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id or uuid.uuid4()
        self.user_id = user_id
        self.key_hash = key_hash
        self.name = name
        self.last_used_at = last_used_at
        self.created_at = created_at or datetime.now(timezone.utc)


class UsageLogRecord:
    __slots__ = ("id", "user_id", "endpoint", "pages_processed", "created_at")

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        user_id: uuid.UUID,
        endpoint: str,
        pages_processed: int = 0,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id or uuid.uuid4()
        self.user_id = user_id
        self.endpoint = endpoint
        self.pages_processed = pages_processed
        self.created_at = created_at or datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────
# DDL – all tables and indexes
# ──────────────────────────────────────────────────────────────────────

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    full_name       TEXT NOT NULL DEFAULT '',
    company_name    TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT 'estimator'
                    CHECK (role IN ('admin', 'estimator', 'viewer')),
    plan            TEXT NOT NULL DEFAULT 'free'
                    CHECK (plan IN ('free', 'pro', 'enterprise')),
    stripe_customer_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DDL_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    input_json    JSONB NOT NULL DEFAULT '{}',
    result_json   JSONB,
    error         TEXT
);
"""

_DDL_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_subscription_id  TEXT NOT NULL UNIQUE,
    stripe_price_id         TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'past_due', 'canceled')),
    current_period_start    TIMESTAMPTZ NOT NULL DEFAULT now(),
    current_period_end      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DDL_API_KEYS = """
CREATE TABLE IF NOT EXISTS api_keys (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash      TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT 'default',
    last_used_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DDL_USAGE_LOGS = """
CREATE TABLE IF NOT EXISTS usage_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint          TEXT NOT NULL,
    pages_processed   INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_INDEXES = [
    # users
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);",
    "CREATE INDEX IF NOT EXISTS idx_users_stripe_customer_id ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;",
    # jobs
    "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user_status_created ON jobs(user_id, status, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);",
    # subscriptions
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_subscription_id ON subscriptions(stripe_subscription_id);",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);",
    # api_keys
    "CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);",
    # usage_logs
    "CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_usage_logs_user_created ON usage_logs(user_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_usage_logs_endpoint ON usage_logs(endpoint);",
]


# ──────────────────────────────────────────────────────────────────────
# Database class
# ──────────────────────────────────────────────────────────────────────


class PgDatabase:
    """Async PostgreSQL database wrapper backed by an asyncpg pool."""

    def __init__(self, database_url: str, *, min_size: int = 2, max_size: int = 20) -> None:
        self._database_url = database_url
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def init(self) -> None:
        """Create the connection pool and ensure all tables exist."""
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=self._min_size,
            max_size=self._max_size,
        )
        await self._create_tables()

    async def close(self) -> None:
        """Gracefully close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _create_tables(self) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            for ddl in (_DDL_USERS, _DDL_JOBS, _DDL_SUBSCRIPTIONS, _DDL_API_KEYS, _DDL_USAGE_LOGS):
                await conn.execute(ddl)
            for idx_ddl in _INDEXES:
                await conn.execute(idx_ddl)

    # ── Internal helper ──────────────────────────────────────────────

    def _acquire(self) -> asyncpg.pool.PoolAcquireContext:
        assert self._pool is not None, "Database not initialised – call init() first"
        return self._pool.acquire()

    # ──────────────────────────────────────────────────────────────────
    # Users
    # ──────────────────────────────────────────────────────────────────

    async def create_user(self, rec: UserRecord) -> UserRecord:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (id, email, hashed_password, full_name, company_name,
                                   role, plan, stripe_customer_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
                """,
                rec.id,
                rec.email,
                rec.hashed_password,
                rec.full_name,
                rec.company_name,
                rec.role,
                rec.plan,
                rec.stripe_customer_id,
                rec.created_at,
                rec.updated_at,
            )
        return _row_to_user(row)

    async def get_user_by_id(self, user_id: uuid.UUID) -> UserRecord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return _row_to_user(row) if row else None

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        return _row_to_user(row) if row else None

    async def get_user_by_stripe_customer_id(self, stripe_customer_id: str) -> UserRecord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE stripe_customer_id = $1",
                stripe_customer_id,
            )
        return _row_to_user(row) if row else None

    async def update_user(self, user_id: uuid.UUID, **fields: Any) -> UserRecord | None:
        """Update arbitrary user fields.  ``updated_at`` is auto-set."""
        if not fields:
            return await self.get_user_by_id(user_id)
        fields["updated_at"] = datetime.now(timezone.utc)
        set_clause = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields.keys()))
        values: list[Any] = [user_id, *fields.values()]
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE users SET {set_clause} WHERE id = $1 RETURNING *",
                *values,
            )
        return _row_to_user(row) if row else None

    async def delete_user(self, user_id: uuid.UUID) -> bool:
        async with self._acquire() as conn:
            result = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        return result == "DELETE 1"

    # ──────────────────────────────────────────────────────────────────
    # Jobs
    # ──────────────────────────────────────────────────────────────────

    async def create_job(self, rec: JobRecordPg) -> JobRecordPg:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO jobs (job_id, user_id, status, created_at, updated_at,
                                  started_at, completed_at, input_json, result_json, error)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
                """,
                rec.job_id,
                rec.user_id,
                rec.status,
                rec.created_at,
                rec.updated_at,
                rec.started_at,
                rec.completed_at,
                json.dumps(rec.input),
                json.dumps(rec.result) if rec.result is not None else None,
                rec.error,
            )
        return _row_to_job(row)

    async def get_job(self, job_id: str, *, user_id: uuid.UUID | None = None) -> JobRecordPg | None:
        async with self._acquire() as conn:
            if user_id is None:
                row = await conn.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM jobs WHERE job_id = $1 AND user_id = $2",
                    job_id,
                    user_id,
                )
        return _row_to_job(row) if row else None

    async def update_job(
        self,
        job_id: str,
        *,
        status: str,
        updated_at: datetime,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> bool:
        params: list[Any] = [
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
            SET status = $1,
                updated_at = $2,
                started_at = COALESCE($3, started_at),
                completed_at = $4,
                result_json = $5,
                error = $6
            WHERE job_id = $7
        """
        if user_id is not None:
            query += " AND user_id = $8"
            params.append(user_id)
        async with self._acquire() as conn:
            result_tag = await conn.execute(query, *params)
        return "UPDATE 1" == result_tag

    async def transition_job_if_current(
        self,
        job_id: str,
        *,
        current_status: str,
        status: str,
        updated_at: datetime,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> bool:
        params: list[Any] = [
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
            SET status = $1,
                updated_at = $2,
                started_at = COALESCE($3, started_at),
                completed_at = $4,
                result_json = $5,
                error = $6
            WHERE job_id = $7
              AND status = $8
        """
        if user_id is not None:
            query += " AND user_id = $9"
            params.append(user_id)
        async with self._acquire() as conn:
            result_tag = await conn.execute(query, *params)
        return "UPDATE 1" == result_tag

    async def list_jobs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> list[JobRecordPg]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        conditions: list[str] = []
        params: list[Any] = []
        idx = 0

        if status is not None:
            idx += 1
            conditions.append(f"status = ${idx}")
            params.append(status)

        if user_id is not None:
            idx += 1
            conditions.append(f"user_id = ${idx}")
            params.append(user_id)

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        idx += 1
        params.append(limit)
        idx += 1
        params.append(offset)

        query = f"""
            SELECT * FROM jobs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${idx - 1} OFFSET ${idx}
        """

        async with self._acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [_row_to_job(r) for r in rows]

    async def count_jobs(
        self,
        *,
        status: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> int:
        conditions: list[str] = []
        params: list[Any] = []
        idx = 0

        if status is not None:
            idx += 1
            conditions.append(f"status = ${idx}")
            params.append(status)

        if user_id is not None:
            idx += 1
            conditions.append(f"user_id = ${idx}")
            params.append(user_id)

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        query = f"SELECT COUNT(*) AS total FROM jobs{where_clause}"

        async with self._acquire() as conn:
            row = await conn.fetchrow(query, *params)
        return int(row["total"]) if row else 0

    async def list_jobs_for_prune(
        self,
        *,
        statuses: list[str],
        updated_before: datetime | None,
        limit: int,
        user_id: uuid.UUID | None = None,
    ) -> list[JobRecordPg]:
        if not statuses:
            return []
        limit = max(1, min(limit, 1000))

        conditions: list[str] = []
        params: list[Any] = []
        idx = 0

        placeholders = ", ".join(f"${i}" for i in range(1, len(statuses) + 1))
        conditions.append(f"status IN ({placeholders})")
        params.extend(statuses)
        idx = len(statuses)

        if user_id is not None:
            idx += 1
            conditions.append(f"user_id = ${idx}")
            params.append(user_id)

        if updated_before is not None:
            idx += 1
            conditions.append(f"updated_at <= ${idx}")
            params.append(updated_before)

        idx += 1
        params.append(limit)

        where_clause = " WHERE " + " AND ".join(conditions)
        query = f"SELECT * FROM jobs{where_clause} ORDER BY updated_at ASC LIMIT ${idx}"

        async with self._acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [_row_to_job(r) for r in rows]

    async def delete_job(self, job_id: str, *, user_id: uuid.UUID | None = None) -> bool:
        async with self._acquire() as conn:
            if user_id is None:
                result_tag = await conn.execute("DELETE FROM jobs WHERE job_id = $1", job_id)
            else:
                result_tag = await conn.execute(
                    "DELETE FROM jobs WHERE job_id = $1 AND user_id = $2",
                    job_id,
                    user_id,
                )
        return "DELETE 1" == result_tag

    # ──────────────────────────────────────────────────────────────────
    # Subscriptions
    # ──────────────────────────────────────────────────────────────────

    async def create_subscription(self, rec: SubscriptionRecord) -> SubscriptionRecord:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO subscriptions
                    (id, user_id, stripe_subscription_id, stripe_price_id,
                     status, current_period_start, current_period_end, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
                """,
                rec.id,
                rec.user_id,
                rec.stripe_subscription_id,
                rec.stripe_price_id,
                rec.status,
                rec.current_period_start,
                rec.current_period_end,
                rec.created_at,
            )
        return _row_to_subscription(row)

    async def get_subscription_by_stripe_id(self, stripe_subscription_id: str) -> SubscriptionRecord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE stripe_subscription_id = $1",
                stripe_subscription_id,
            )
        return _row_to_subscription(row) if row else None

    async def list_subscriptions_for_user(
        self, user_id: uuid.UUID, *, status: str | None = None
    ) -> list[SubscriptionRecord]:
        if status is not None:
            async with self._acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM subscriptions WHERE user_id = $1 AND status = $2 ORDER BY created_at DESC",
                    user_id,
                    status,
                )
        else:
            async with self._acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM subscriptions WHERE user_id = $1 ORDER BY created_at DESC",
                    user_id,
                )
        return [_row_to_subscription(r) for r in rows]

    async def update_subscription_status(
        self, subscription_id: uuid.UUID, status: str
    ) -> SubscriptionRecord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE subscriptions SET status = $1 WHERE id = $2 RETURNING *",
                status,
                subscription_id,
            )
        return _row_to_subscription(row) if row else None

    async def update_subscription(
        self, subscription_id: uuid.UUID, **fields: Any
    ) -> SubscriptionRecord | None:
        """Update arbitrary subscription fields."""
        if not fields:
            return await self.get_subscription_by_stripe_id(
                # Can't look up by ID without a fetch; just return None
                # Caller should use get methods directly if no fields.
                ""
            )
        set_parts: list[str] = []
        values: list[Any] = []
        idx = 2  # $1 is subscription_id
        for key, val in fields.items():
            set_parts.append(f"{key} = ${idx}")
            values.append(val)
            idx += 1
        set_clause = ", ".join(set_parts)
        values.insert(0, subscription_id)
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE subscriptions SET {set_clause} WHERE id = $1 RETURNING *",
                *values,
            )
        return _row_to_subscription(row) if row else None

    # ──────────────────────────────────────────────────────────────────
    # API Keys
    # ──────────────────────────────────────────────────────────────────

    async def create_api_key(self, rec: ApiKeyRecord) -> ApiKeyRecord:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO api_keys (id, user_id, key_hash, name, last_used_at, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                rec.id,
                rec.user_id,
                rec.key_hash,
                rec.name,
                rec.last_used_at,
                rec.created_at,
            )
        return _row_to_api_key(row)

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM api_keys WHERE key_hash = $1", key_hash
            )
        return _row_to_api_key(row) if row else None

    async def list_api_keys_for_user(self, user_id: uuid.UUID) -> list[ApiKeyRecord]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM api_keys WHERE user_id = $1 ORDER BY created_at DESC",
                user_id,
            )
        return [_row_to_api_key(r) for r in rows]

    async def touch_api_key_last_used(self, key_id: uuid.UUID) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE api_keys SET last_used_at = now() WHERE id = $1",
                key_id,
            )

    async def delete_api_key(self, key_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> bool:
        async with self._acquire() as conn:
            if user_id is None:
                result_tag = await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)
            else:
                result_tag = await conn.execute(
                    "DELETE FROM api_keys WHERE id = $1 AND user_id = $2",
                    key_id,
                    user_id,
                )
        return "DELETE 1" == result_tag

    # ──────────────────────────────────────────────────────────────────
    # Usage Logs
    # ──────────────────────────────────────────────────────────────────

    async def create_usage_log(self, rec: UsageLogRecord) -> UsageLogRecord:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO usage_logs (id, user_id, endpoint, pages_processed, created_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                rec.id,
                rec.user_id,
                rec.endpoint,
                rec.pages_processed,
                rec.created_at,
            )
        return _row_to_usage_log(row)

    async def list_usage_logs_for_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UsageLogRecord]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM usage_logs
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )
        return [_row_to_usage_log(r) for r in rows]

    async def count_usage_for_user(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> int:
        if since is not None:
            async with self._acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS total FROM usage_logs WHERE user_id = $1 AND created_at >= $2",
                    user_id,
                    since,
                )
        else:
            async with self._acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS total FROM usage_logs WHERE user_id = $1",
                    user_id,
                )
        return int(row["total"]) if row else 0

    async def sum_pages_processed_for_user(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> int:
        if since is not None:
            async with self._acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(pages_processed), 0) AS total FROM usage_logs WHERE user_id = $1 AND created_at >= $2",
                    user_id,
                    since,
                )
        else:
            async with self._acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(pages_processed), 0) AS total FROM usage_logs WHERE user_id = $1",
                    user_id,
                )
        return int(row["total"]) if row else 0

    async def count_usage_for_user_by_endpoint(
        self,
        user_id: uuid.UUID,
        *,
        endpoint: str,
        since: datetime | None = None,
    ) -> int:
        """Count usage log entries for a specific endpoint (e.g. job creation)."""
        if since is not None:
            async with self._acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS total FROM usage_logs WHERE user_id = $1 AND endpoint = $2 AND created_at >= $3",
                    user_id,
                    endpoint,
                    since,
                )
        else:
            async with self._acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS total FROM usage_logs WHERE user_id = $1 AND endpoint = $2",
                    user_id,
                    endpoint,
                )
        return int(row["total"]) if row else 0


# ──────────────────────────────────────────────────────────────────────
# Row → Record mappers
# ──────────────────────────────────────────────────────────────────────


def _row_to_user(row: asyncpg.Record) -> UserRecord:
    return UserRecord(
        id=row["id"],
        email=row["email"],
        hashed_password=row["hashed_password"],
        full_name=row["full_name"],
        company_name=row["company_name"],
        role=row["role"],
        plan=row["plan"],
        stripe_customer_id=row["stripe_customer_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_job(row: asyncpg.Record) -> JobRecordPg:
    raw_input = row["input_json"]
    raw_result = row["result_json"]
    input_data = json.loads(raw_input) if isinstance(raw_input, str) else (raw_input or {})
    result_data = json.loads(raw_result) if isinstance(raw_result, str) else (raw_result if raw_result else None)
    return JobRecordPg(
        job_id=row["job_id"],
        user_id=row["user_id"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        input=input_data,
        result=result_data,
        error=row["error"],
    )


def _row_to_subscription(row: asyncpg.Record) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=row["id"],
        user_id=row["user_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        stripe_price_id=row["stripe_price_id"],
        status=row["status"],
        current_period_start=row["current_period_start"],
        current_period_end=row["current_period_end"],
        created_at=row["created_at"],
    )


def _row_to_api_key(row: asyncpg.Record) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row["id"],
        user_id=row["user_id"],
        key_hash=row["key_hash"],
        name=row["name"],
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
    )


def _row_to_usage_log(row: asyncpg.Record) -> UsageLogRecord:
    return UsageLogRecord(
        id=row["id"],
        user_id=row["user_id"],
        endpoint=row["endpoint"],
        pages_processed=row["pages_processed"],
        created_at=row["created_at"],
    )


# ──────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ──────────────────────────────────────────────────────────────────────

_db_instance: PgDatabase | None = None


async def init_db() -> PgDatabase:
    """Create and initialise the global PgDatabase instance."""
    global _db_instance
    _db_instance = PgDatabase(settings.database_url)
    await _db_instance.init()
    return _db_instance


async def close_db() -> None:
    """Shut down the global PgDatabase instance."""
    global _db_instance
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None


async def get_db() -> AsyncGenerator[PgDatabase, None]:
    """FastAPI ``Depends``-compatible dependency that yields the PgDatabase."""
    if _db_instance is None:
        raise RuntimeError("Database not initialised – call init_db() at startup")
    yield _db_instance
