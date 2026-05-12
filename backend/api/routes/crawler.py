"""
api/routes/crawler.py — Crawler trigger and status endpoints.

POST /api/crawler/run?type=all|schemes|funding|jobs  → Trigger a crawl
GET  /api/crawler/status                              → Last run status
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.api.deps import DbSession
from backend.services.crawler_orchestrator import CrawlerOrchestrator, OrchestratorRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawler", tags=["crawler"])

_orchestrator = CrawlerOrchestrator()


# ── Schemas ─────────────────────────────────────────────────────────────────


class CrawlRunResponse(BaseModel):
    status: str
    runs: dict
    total_collected: int
    total_persisted: int


class CrawlerStatusResponse(BaseModel):
    run_count: int
    last_run: dict | None
    current_time: str


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/run", response_model=CrawlRunResponse)
async def run_crawler(
    session: DbSession,
    type: str = Query("all", description="Crawler type: all, schemes, funding, jobs"),
):
    if type == "all":
        run = await _orchestrator.run_all(session)
    elif type == "schemes":
        run = await _orchestrator.run_schemes(session)
    elif type == "funding":
        run = await _orchestrator.run_funding(session)
    elif type == "jobs":
        run = await _orchestrator.run_jobs(session)
    else:
        return CrawlRunResponse(
            status="error",
            runs={"error": f"Unknown type: {type}"},
            total_collected=0,
            total_persisted=0,
        )

    runs_dict = {}
    for name, r in run.runs.items():
        runs_dict[name] = {
            "status": r.status,
            "collected": r.items_collected,
            "persisted": r.items_persisted,
            "errors": r.errors[:5],
        }

    return CrawlRunResponse(
        status="completed" if run.all_succeeded else "partial_failures",
        runs=runs_dict,
        total_collected=run.total_collected,
        total_persisted=run.total_persisted,
    )


@router.get("/status", response_model=CrawlerStatusResponse)
async def crawler_status():
    last = _orchestrator.last_run
    last_dict = None
    if last:
        last_dict = {
            "started_at": last.started_at.isoformat(),
            "finished_at": last.finished_at.isoformat() if last.finished_at else None,
            "runs": {
                name: {
                    "status": r.status,
                    "collected": r.items_collected,
                    "persisted": r.items_persisted,
                }
                for name, r in last.runs.items()
            },
            "total_collected": last.total_collected,
            "total_persisted": last.total_persisted,
        }

    return CrawlerStatusResponse(
        run_count=_orchestrator._run_count,
        last_run=last_dict,
        current_time=datetime.now(UTC).isoformat(),
    )