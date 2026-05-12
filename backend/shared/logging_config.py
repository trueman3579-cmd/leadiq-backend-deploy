"""
shared/logging_config.py — Structured logging via structlog + optional Sentry.

Call configure_logging() once at app startup (in lifespan or __main__).
Use get_logger(__name__) everywhere instead of logging.getLogger.

Outputs:
  - DEV  mode: coloured human-readable console renderer
  - PROD mode: JSON lines (structlog.processors.JSONRenderer)

Sentry integration is activated when SENTRY_DSN is non-empty in config.
"""
from __future__ import annotations

import logging
import sys

import structlog

from backend.shared.config import settings


def configure_logging() -> None:
    """Wire structlog and optionally Sentry. Call once at startup."""
    level_name = settings.LOG_LEVEL.upper()
    level_int  = getattr(logging, level_name, logging.INFO)

    # Standard library root logger — lets uvicorn/fastapi logs flow through
    logging.basicConfig(
        format   = "%(message)s",
        stream   = sys.stdout,
        level    = level_int,
        force    = True,
    )

    is_dev = settings.DEBUG

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_dev:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors            = shared_processors + [renderer],
        wrapper_class         = structlog.make_filtering_bound_logger(level_int),
        context_class         = dict,
        logger_factory        = structlog.PrintLoggerFactory(),
        cache_logger_on_first_use = True,
    )

    # ── Sentry (optional) ──────────────────────────────────────────────────────
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

            sentry_sdk.init(
                dsn                    = settings.SENTRY_DSN,
                environment            = "development" if is_dev else "production",
                traces_sample_rate     = 0.2,
                profiles_sample_rate   = 0.1,
                integrations           = [
                    FastApiIntegration(transaction_style="endpoint"),
                    SqlalchemyIntegration(),
                ],
                send_default_pii       = False,
            )
            get_logger(__name__).info("sentry_initialised", dsn_prefix=settings.SENTRY_DSN[:20])
        except Exception as exc:
            get_logger(__name__).warning("sentry_init_failed", error=str(exc))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger for *name*."""
    return structlog.get_logger(name)
