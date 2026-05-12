"""
api/routes/funding.py — Funding Events API endpoint.

GET /api/funding → List funding events from DB
GET /api/funding/stats → Funding stats
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import List

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from backend.api.deps import DbSession
from backend.shared.repository import FundingEventRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/funding", tags=["funding"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class FundingEventResponse(BaseModel):
    id: str
    company_name: str
    amount: str | None
    round_type: str | None
    date: datetime | None
    source: str
    location: str | None
    industry: str | None
    trust_score: float
    is_verified: bool

    model_config = ConfigDict(from_attributes=True)



class FundingListResponse(BaseModel):
    events: List[FundingEventResponse]
    total: int
    stats: dict
    last_updated: str


class FundingStatsResponse(BaseModel):
    total: int
    verified: int
    sources: List[str]
    last_updated: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=FundingListResponse)
async def list_funding(
    session: DbSession,
    source: str = Query("", description="Filter by source"),
    industry: str = Query("", description="Filter by industry"),
    limit: int = Query(200, ge=1, le=500),
):
    repo = FundingEventRepo(session)
    events = await repo.list_all(
        source=source or None,
        industry=industry or None,
        min_trust=0.0,
        limit=limit,
    )
    stats = await repo.get_stats()

    return FundingListResponse(
        events=[FundingEventResponse.model_validate(e) for e in events],
        total=len(events),
        stats=stats,
        last_updated=datetime.now(UTC).isoformat(),
    )


@router.get("/stats", response_model=FundingStatsResponse)
async def funding_stats(session: DbSession):
    repo = FundingEventRepo(session)
    stats = await repo.get_stats()
    return FundingStatsResponse(
        total=stats["total"],
        verified=stats["verified"],
        sources=stats["sources"],
        last_updated=datetime.now(UTC).isoformat(),
    )


@router.get("/recent")
async def recent_funding(
    session: DbSession,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200),
):
    repo = FundingEventRepo(session)
    events = await repo.get_recent(hours=hours, limit=limit)
    return FundingListResponse(
        events=[FundingEventResponse.model_validate(e) for e in events],
        total=len(events),
        stats={},
        last_updated=datetime.now(UTC).isoformat(),
    )


@router.get("/health")
async def funding_health(session: DbSession):
    repo = FundingEventRepo(session)
    stats = await repo.get_stats()
    return {
        "status": "ok",
        "service": "funding-events",
        "db_records": stats["total"],
        "sources": stats["sources"],
    }