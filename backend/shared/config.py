"""
shared/config.py — Pydantic BaseSettings for all environment variables.
Single source of truth — import `settings` everywhere, never os.getenv directly.
"""
from __future__ import annotations

from datetime import timezone, UTC
from typing import Any

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", case_sensitive=True)
    # ── Server ────────────────────────────────────────────────────────────────
    APP_NAME: str = "LeadIQ"
    DEBUG: bool = False
    SECRET_KEY: str  # Must be set via environment variable in production

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://leadiq-dashboard.vercel.app",
        "https://leadiq-dashboard-*.vercel.app",
        "https://leadiq-dashboard-git-*.vercel.app",
    ]

    # ── Gemini / GCP ─────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "us-central1"

    # ── Redis Stream names ────────────────────────────────────────────────────
    STREAM_COLLECTED: str = "lead:collected"
    STREAM_ANALYZED: str = "lead:analyzed"
    STREAM_SCORED: str = "lead:scored"
    STREAM_RANKED: str = "lead:ranked"
    STREAM_OUTREACH: str = "lead:outreach"
    STREAM_CRM_UPDATE: str = "lead:crm_update"
    STREAM_LOGS: str = "system:logs"

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── External API Keys ─────────────────────────────────────────────────────
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "LeadIQ/1.0"
    TWITTER_BEARER_TOKEN: str = ""
    GITHUB_TOKEN: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    NVIDIA_API_KEY: str = ""
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASS: str = ""  # Must be set in production
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "phi3:mini"
    OLLAMA_CLOUD_URL: str = ""

    # ── Enrichment API Keys ───────────────────────────────────────────────────
    HUNTER_API_KEY: str = ""       # Hunter.io email finder
    CLEARBIT_API_KEY: str = ""     # Clearbit company enrichment

    # ── Telegram ──────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""       # For outbound notifications (bot API)
    TELEGRAM_CHAT_ID: str = ""         # For outbound notifications
    TELEGRAM_API_ID: str = ""          # For inbound scraping (my.telegram.org)
    TELEGRAM_API_HASH: str = ""        # For inbound scraping (my.telegram.org)

    # ── Auth (JWT) ────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str  # Must be set via environment variable in production
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480       # 8 hours
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str  # Must be set via environment variable in production

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "120/minute"
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_EXPENSIVE: str = "5/minute"

    # ── Gemini Token Budget (Day 10: Cost Stable) ──────────────────────────────
    GEMINI_DAILY_BUDGET: int = 2_000_000
    GEMINI_HOURLY_BUDGET: int = 83_333      # 2M / 24 hours
    GEMINI_QUEUE_STREAM: str = "leadiq:gemini:queue"
    GEMINI_QUEUE_MAX_SIZE: int = 500

    # ── Source Quality (Day 11: Source Audit) ──────────────────────────────────
    DISABLED_SOURCES: str = ""              # comma-separated, e.g. "twitter,rss"
    SOURCE_QUALIFICATION_THRESHOLD: float = 0.15
    SOURCE_AUDIT_WINDOW_DAYS: int = 7

    # ── MCP ─────────────────────────────────────────────────────────────────
    MCP_API_KEY: str = ""  # Must be set in production; empty = reject all requests

    # ── Observability ─────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"

    # ── Helper Methods ─────────────────────────────────────────────────────────
    @property
    def disabled_sources(self) -> set[str]:
        """Parsed disabled source names (comma-separated DISABLED_SOURCES)."""
        return {s.strip() for s in self.DISABLED_SOURCES.split(",") if s.strip()}

    def validate_production_requirements(self) -> None:
        """Fail fast for unsafe production configuration."""
        if self.DEBUG:
            return
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY must be set and at least 32 characters in production.")
        if not self.JWT_SECRET_KEY or len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be set and at least 32 characters in production.")
        if not self.ADMIN_PASSWORD:
            raise ValueError("ADMIN_PASSWORD must be set in production.")
        if not self.ALLOWED_ORIGINS:
            raise ValueError("ALLOWED_ORIGINS cannot be empty in production.")
        if "*" in self.ALLOWED_ORIGINS:
            raise ValueError("ALLOWED_ORIGINS cannot contain '*' in production.")

    def get_timezone(self) -> timezone:
        """Get the configured timezone (default UTC)."""
        return UTC

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Compatibility shim for Pydantic v1/v2 dump."""
        return dict(self)


settings = Settings()
