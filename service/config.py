"""Pydantic Settings configuration for AI-Estimator SaaS.

All values are read from environment variables with sensible defaults
where appropriate.  Instantiate once at application startup:

    from service.config import Settings
    settings = Settings()
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────
    app_name: str = "AI-Estimator"
    app_version: str = "0.1.0"

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = "postgresql://postgres:postgres@localhost:5432/ai_estimator"

    # ── JWT / Auth ───────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── Stripe ───────────────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_free: str = ""
    stripe_price_pro: str = ""
    stripe_price_enterprise: str = ""

    # ── Redis ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── CORS ─────────────────────────────────────────────────────────
    cors_origins: str = (
        "http://127.0.0.1:8000,"
        "http://localhost:8000,"
        "http://127.0.0.1:3000,"
        "http://localhost:3000"
    )

    # ── Upload limits ────────────────────────────────────────────────
    upload_max_files: int = 50
    upload_max_size_mb: int = 100

    # ── Rate limiting ────────────────────────────────────────────────
    rate_limit_per_minute: int = 60


# Convenience singleton – import and use `settings.attribute`.
settings = Settings()
