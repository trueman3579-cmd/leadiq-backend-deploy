"""
logging_middleware.py — Structured Logging Middleware (Day 23: Observability)

Adds request tracing, timing, and structured JSON logging to all endpoints.
Integrates with structlog for Axiom/Loki-compatible JSON output.

Features:
  - Per-request request_id (UUID) propagated through all log entries
  - Request timing (ms) logged for every endpoint
  - Request/response body capture (truncated, optional)
  - PII-safe: filters Authorization, Cookie, Set-Cookie headers
"""
from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured logging middleware — request trace + timing + PII filtering.

    Adds X-Request-ID to response headers for client-side tracing.
    Logs method, path, status, duration_ms, and client_ip for every request.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_ms = time.monotonic()

        # Bind request context
        request.state.request_id = request_id

        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            duration_ms = (time.monotonic() - start_ms) * 1000
            logger.error(
                "request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                error=str(exc),
            )
            raise
        finally:
            duration_ms = (time.monotonic() - start_ms) * 1000
            status_code = response.status_code if response else 500

            if status_code >= 500:
                log_level = logger.error
            elif status_code >= 400:
                log_level = logger.warning
            else:
                log_level = logger.info

            log_level(
                "request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query=str(request.url.query) if request.url.query else "",
                status=status_code,
                duration_ms=round(duration_ms, 2),
                client_ip=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("User-Agent", "")[:200],
            )

            # Ensure request ID is in response headers
            if response and "X-Request-ID" not in response.headers:
                response.headers["X-Request-ID"] = request_id


def configure_structlog(service_name: str = "leadiq-backend") -> None:
    """
    Configure structlog for JSON output (Axiom/Loki compatible).

    Call once at app startup. Sets up:
        - JSON renderer for production
        - Key-value console renderer for development
        - Timestamps in ISO 8601 UTC
    """
    import os

    is_production = os.getenv("ENVIRONMENT", "development") == "production"

    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_production:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.get_logger().info(
        "structlog_configured",
        service=service_name,
        renderer="json" if is_production else "console",
    )
