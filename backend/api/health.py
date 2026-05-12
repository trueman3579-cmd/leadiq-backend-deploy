"""
health.py — Watchdog Health Probe (Day 25)

Comprehensive health endpoint for auto-restart orchestration.
Returns DB, Redis, Gemini, and DLQ status. Used by Kubernetes/Docker health probes.

Endpoint: GET /api/health (no auth required)
"""
from __future__ import annotations

from fastapi import APIRouter
from datetime import UTC

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_probe():
    """
    Full health check for watchdog / orchestrator.

    Returns 200 if all critical services are healthy.
    Returns 503 if any critical service is down.
    """
    from datetime import datetime
    from fastapi.responses import JSONResponse

    checks: dict[str, dict] = {}
    healthy = True

    # Database
    try:
        from backend.shared.db import get_db_session
        from sqlalchemy import text

        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}
        healthy = False

    # Redis
    try:
        from backend.shared.stream import redis_stream

        r = redis_stream._r
        if r:
            await r.ping()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "not_connected"}
            healthy = False
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)}
        healthy = False

    # Gemini API
    try:
        from backend.shared.config import settings

        if settings.GEMINI_API_KEY:
            checks["gemini"] = {"status": "configured"}
        else:
            checks["gemini"] = {"status": "not_configured"}
    except Exception as e:
        checks["gemini"] = {"status": "error", "error": str(e)}

    # DLQ
    try:
        from backend.shared.db import get_db_session
        from backend.workers.dlq import DLQWorker

        async with get_db_session() as session:
            worker = DLQWorker(session, redis_stream._r)
            stats = await worker.get_stats()
            checks["dlq"] = {
                "status": "ok",
                "total_pending": stats["total"],
                "failed_permanent": stats["failed_permanent"],
            }
    except Exception as e:
        checks["dlq"] = {"status": "error", "error": str(e)}

    # Source metrics
    try:
        from backend.workers.source_metrics import SOURCES
        checks["sources"] = {"status": "ok", "registered": len(SOURCES)}
    except Exception as e:
        checks["sources"] = {"status": "error", "error": str(e)}

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if healthy else "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": "0.1.0",
            "checks": checks,
        },
    )


@router.get("/health/live")
async def liveness_probe():
    """Minimal liveness probe — just confirms process is alive."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness_probe():
    """Readiness probe — confirms DB + Redis are connected."""
    ok = True
    try:
        from backend.shared.db import get_db_session
        from sqlalchemy import text
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        ok = False

    try:
        from backend.shared.stream import redis_stream
        if redis_stream._r:
            await redis_stream._r.ping()
        else:
            ok = False
    except Exception:
        ok = False

    if ok:
        return {"status": "ready"}
    else:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "not_ready"})


@router.get("/health/celery")
async def celery_health_probe():
    """Celery worker health — broker, workers, and queue depth."""
    from datetime import datetime
    from fastapi.responses import JSONResponse

    from backend.workers.pipeline import celery_app
    from backend.shared.stream import redis_stream

    checks: dict[str, dict] = {}
    healthy = True

    # Broker
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1)
        checks["broker"] = {"status": "ok"}
    except Exception as exc:
        checks["broker"] = {"status": "error", "error": str(exc)}
        healthy = False

    # Active workers
    try:
        inspect = celery_app.control.inspect()
        active = inspect.active() or {}
        checks["workers"] = {
            "status": "ok",
            "count": len(active),
            "names": list(active.keys()),
        }
    except Exception as exc:
        checks["workers"] = {"status": "error", "error": str(exc)}
        healthy = False

    # Queue depths
    try:
        r = redis_stream._r
        if r:
            queues = ["celery", "default", "pipeline"]
            depths = {}
            for q in queues:
                try:
                    depths[q] = await r.llen(q)
                except Exception:
                    depths[q] = None
            checks["queues"] = {"status": "ok", "depths": depths}
        else:
            checks["queues"] = {"status": "not_connected"}
    except Exception as exc:
        checks["queues"] = {"status": "error", "error": str(exc)}

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if healthy else "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": checks,
        },
    )
