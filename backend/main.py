"""
LeadIQ Backend — FastAPI Server
B2B Intelligence Pipeline — Full stack: collectors → analyzer → scorer → persist
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.shared.config import settings
from backend.shared.logging_config import configure_logging, get_logger
from backend.shared.stream import redis_stream
from backend.services.velocity import velocity_tracker
from backend.shared.db import engine
from sqlalchemy import text
from backend.api import health
from backend.api.routes import leads, stats, admin, profile, auth, mcp, live_feed
from backend.api.routes import jobs, government, scoring, outreach, schemes, validate, nlp, ml
from backend.api.routes import crawler, funding, models
from backend.api.routes import ingest
from backend.api.mcp_server import mcp_app

# ── Bootstrap logging + Sentry before anything else ──────────────────────────
configure_logging()
logger = get_logger(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("leadiq_startup", version="2.0.0")
    settings.validate_production_requirements()
    # Startup: verify DB connection first (Hussein Nasser - fail fast)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("db_connection_verified", port=6543, pool="NullPool")
    except Exception as exc:
        logger.error("db_startup_failed", error=str(exc))
        raise  # HARD FAIL: don't start without DB
    # Startup: connect Redis stream bus + velocity tracker
    try:
        await redis_stream.connect()
        logger.info("redis_stream_connected")
    except Exception as exc:
        logger.warning("redis_stream_skipped", error=str(exc))
    try:
        await velocity_tracker.connect()
        logger.info("velocity_tracker_connected")
    except Exception as exc:
        logger.warning("velocity_tracker_skipped", error=str(exc))
    yield
    # Shutdown: dispose DB engine cleanly
    try:
        await engine.dispose()
        logger.info("db_engine_disposed")
    except Exception:
        pass
    try:
        await redis_stream.disconnect()
        await velocity_tracker.disconnect()
    except Exception:
        pass
    logger.info("leadiq_shutdown")


app = FastAPI(
    title="LeadIQ API",
    description="AI-powered B2B lead intelligence pipeline",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── Rate limiting error handler ───────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(stats.router)
app.include_router(admin.router)
app.include_router(profile.router)
app.include_router(mcp.router)
app.include_router(live_feed.router)
app.include_router(jobs.router)
app.include_router(government.router)
app.include_router(scoring.router)
app.include_router(outreach.router)
app.include_router(schemes.router)
app.include_router(validate.router)
app.include_router(nlp.router)
app.include_router(ml.router)
app.include_router(crawler.router)
app.include_router(funding.router)
app.include_router(models.router)
app.include_router(ingest.router)

# ── MCP server (Streamable HTTP at /mcp) ─────────────────────────────────
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

