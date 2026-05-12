"""
api/routes/schemes.py — REST endpoint for government schemes.

GET /api/schemes → List all government schemes from DB
GET /api/schemes?department=SIDBI → Filter by department
GET /api/schemes?eligibility=startup → Filter by eligibility

Reads from GovScheme table (populated by GovtSchemesCrawler).
Falls back to inline scrape if DB is empty.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import List

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from backend.api.deps import DbSession
from backend.shared.repository import GovSchemeRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schemes", tags=["government-schemes"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class SchemeResponse(BaseModel):
    name: str
    description: str
    eligibility: str
    deadline: str | None
    funding_amount: str | None
    source_url: str
    department: str
    trust_score: float

    model_config = ConfigDict(from_attributes=True)



class SchemesListResponse(BaseModel):
    schemes: List[SchemeResponse]
    total: int
    departments: List[str]
    last_updated: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=SchemesListResponse)
async def list_schemes(
    session: DbSession,
    department: str = Query("", description="Filter by department"),
    min_trust: float = Query(5.0, description="Minimum trust score"),
):
    repo = GovSchemeRepo(session)
    schemes = await repo.list_all(
        department=department or None,
        min_trust=min_trust,
        limit=500,
    )
    departments = await repo.get_departments()

    if not schemes:
        logger.info("gov_schemes_db_empty_falling_back_to_scrape")
        from backend.collectors.government_schemes import GovernmentScraper
        scraper = GovernmentScraper()
        raw = await scraper.scrape_all()
        for s in raw:
            try:
                await repo.upsert({
                    "name": s.name,
                    "description": s.description,
                    "eligibility": s.eligibility,
                    "deadline": s.deadline,
                    "funding_amount": s.funding_amount,
                    "source_url": s.source_url,
                    "department": s.department,
                    "trust_score": s.trust_score,
                })
            except Exception as exc:
                logger.warning("scheme_upsert_fallback_failed", name=s.name, error=str(exc))
        schemes = await repo.list_all(department=department or None, min_trust=min_trust, limit=500)
        departments = await repo.get_departments()

    return SchemesListResponse(
        schemes=[SchemeResponse.model_validate(s) for s in schemes],
        total=len(schemes),
        departments=departments,
        last_updated=datetime.now(UTC).isoformat(),
    )


@router.get("/departments")
async def list_departments(session: DbSession):
    repo = GovSchemeRepo(session)
    depts = await repo.get_departments()
    return {"departments": depts}


@router.get("/health")
async def schemes_health(session: DbSession):
    repo = GovSchemeRepo(session)
    count = await repo.count()
    return {
        "status": "ok",
        "service": "government-schemes",
        "sources": ["data.gov.in", "startupindia.gov.in", "msme.gov.in", "sidbi.in"],
        "db_records": count,
        "trust_level": "maximum (gov domains)",
    }