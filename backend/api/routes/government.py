"""
api/routes/government.py — Government Data API Routes.

Provides endpoints to trigger collection from government sources (DPIIT, MCA21)
and query government-sourced leads with filtering by source, state, sector, band.

The /verify/{cin} endpoint cross-references a company across multiple government
registries.
"""
from __future__ import annotations

import structlog
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DbSession, StreamClient
from backend.events.emitter import emit
from backend.shared.config import settings
from backend.shared.models import Lead
from backend.shared.repository import LeadRepo

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/government", tags=["government"])


# ── Schemas ──────────────────────────────────────────────────────────────────────

class CollectGovRequest(BaseModel):
    """Request body for triggering government data collection."""
    max_results: int = Field(100, ge=1, le=1000, description="Max records to collect")
    filters: dict[str, str] = Field(default_factory=dict, description="Optional source-specific filters")


class CollectGovResponse(BaseModel):
    """Response after triggering government data collection."""
    status: str
    job_id: str
    source: str
    message: str


class GovLeadOut(BaseModel):
    """Simplified lead output for government-sourced leads."""
    id: str
    company_name: str | None = None
    industry: str | None = None
    location: str | None = None
    company_size: str | None = None
    funding_stage: str | None = None
    final_score: float = 0.0
    score_band: str = "cold"
    source: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)



class GovLeadListResponse(BaseModel):
    """Paginated response for government lead queries."""
    total: int
    page: int
    page_size: int
    leads: list[GovLeadOut]


class GovStatsResponse(BaseModel):
    """Statistics for government-sourced leads."""
    total_dpiit: int
    total_mca21: int
    total_gem: int
    total_msme: int
    total_government: int
    band_distribution: dict[str, int]
    by_state: dict[str, int]
    by_sector: dict[str, int]


class ApisetuSearchRequest(BaseModel):
    """Request body for API Setu government data search."""
    cin: str | None = Field(None, description="Corporate Identification Number (MCA21)")
    gstin: str | None = Field(None, description="GST Identification Number (GST verification)")
    udyam: str | None = Field(None, description="Udhyam Aadhaar Number (MSME certification)")


class ApisetuSearchResult(BaseModel):
    """Single API Setu search result."""
    source: str
    status: str  # found | not_found | error
    title: str = ""
    external_id: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class ApisetuSearchResponse(BaseModel):
    """Response from API Setu cross-reference search."""
    results: list[ApisetuSearchResult]
    total_found: int


class VerifyCompanyResponse(BaseModel):
    """Cross-reference company verification result."""
    cin: str
    company_name: str | None = None
    dpiit_status: str | None = None
    mca21_status: str | None = None
    gem_status: str | None = None
    msme_status: str | None = None
    verified_at: str


GOVT_STREAM: str = "lead:govt_collected"
GOVT_SOURCES: list[str] = ["dpiit", "mca21", "gem", "msme", "apisetu_mca21", "apisetu_gst", "apisetu_udyam"]

# ── Collection Endpoints (rate-limited) ──────────────────────────────────────────


@router.post("/collect/dpiit", response_model=CollectGovResponse, status_code=202)
async def collect_dpiit(
    body: CollectGovRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectGovResponse:
    """Trigger DPIIT startup India collection.

    Emits a collection request to the government stream.
    """
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "dpiit",
            "max_results": body.max_results,
            "filters": body.filters,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(GOVT_STREAM, payload)
        await emit("signal_detected", {
            "source": "dpiit",
            "job_id": job_id,
            "stream_event_id": event_id,
        })
        logger.info("dpiit_collection_queued", job_id=job_id)
        return CollectGovResponse(
            status="queued",
            job_id=job_id,
            source="dpiit",
            message="DPIIT collection queued",
        )
    except Exception as exc:
        logger.error("dpiit_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue DPIIT collection") from exc


@router.post("/collect/mca21", response_model=CollectGovResponse, status_code=202)
async def collect_mca21(
    body: CollectGovRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectGovResponse:
    """Trigger MCA21 corporate registry collection."""
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "mca21",
            "max_results": body.max_results,
            "filters": body.filters,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(GOVT_STREAM, payload)
        await emit("signal_detected", {
            "source": "mca21",
            "job_id": job_id,
            "stream_event_id": event_id,
        })
        logger.info("mca21_collection_queued", job_id=job_id)
        return CollectGovResponse(
            status="queued",
            job_id=job_id,
            source="mca21",
            message="MCA21 collection queued",
        )
    except Exception as exc:
        logger.error("mca21_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue MCA21 collection") from exc


# ── Query Endpoints ──────────────────────────────────────────────────────────────


@router.get("/leads", response_model=GovLeadListResponse)
async def query_government_leads(
    session: DbSession,
    user: CurrentUser,
    source: list[str] | None = Query(None, description="Filter by source(s): dpiit, mca21, gem, msme"),
    state: str | None = Query(None, description="Filter by state"),
    sector: str | None = Query(None, description="Filter by industry/sector"),
    band: str | None = Query(None, description="Score band: hot / warm / cool / cold"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> GovLeadListResponse:
    """Query government-sourced leads with optional filters."""
    try:
        sources = source or GOVT_SOURCES
        q = select(Lead).where(Lead.source.in_(sources))

        if state:
            q = q.where(Lead.location.ilike(f"%{state}%"))
        if sector:
            q = q.where(Lead.industry.ilike(f"%{sector}%"))
        if band:
            q = q.where(Lead.score_band == band)

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(Lead.final_score.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        leads = list(result.scalars().all())

        return GovLeadListResponse(
            total=total,
            page=page,
            page_size=page_size,
            leads=[_gov_lead_to_out(lead) for lead in leads],
        )
    except Exception as exc:
        logger.error("government_leads_query_failed", error=str(exc))
        return GovLeadListResponse(total=0, page=page, page_size=page_size, leads=[])


@router.get("/stats", response_model=GovStatsResponse)
async def government_stats(
    session: DbSession,
    user: CurrentUser,
) -> GovStatsResponse:
    """Get government source statistics — counts per source, band, state, sector."""
    try:
        # Total counts per government source
        counts: dict[str, int] = {}
        for src in GOVT_SOURCES:
            result = await session.execute(
                select(func.count(Lead.id)).where(Lead.source == src)
            )
            counts[src] = result.scalar() or 0

        # Band distribution
        band_result = await session.execute(
            select(Lead.score_band, func.count(Lead.id))
            .where(Lead.source.in_(GOVT_SOURCES))
            .group_by(Lead.score_band)
        )
        band_dist: dict[str, int] = {"hot": 0, "warm": 0, "cool": 0, "cold": 0}
        for row in band_result:
            band_dist[row[0]] = row[1]

        # By state
        state_result = await session.execute(
            select(Lead.location, func.count(Lead.id))
            .where(Lead.source.in_(GOVT_SOURCES))
            .where(Lead.location.isnot(None))
            .group_by(Lead.location)
            .order_by(func.count(Lead.id).desc())
            .limit(20)
        )
        by_state: dict[str, int] = {}
        for row in state_result:
            by_state[row[0]] = row[1]

        # By sector (industry)
        sector_result = await session.execute(
            select(Lead.industry, func.count(Lead.id))
            .where(Lead.source.in_(GOVT_SOURCES))
            .where(Lead.industry.isnot(None))
            .group_by(Lead.industry)
            .order_by(func.count(Lead.id).desc())
            .limit(20)
        )
        by_sector: dict[str, int] = {}
        for row in sector_result:
            by_sector[row[0]] = row[1]

        total_gov = sum(counts.values())

        return GovStatsResponse(
            total_dpiit=counts.get("dpiit", 0),
            total_mca21=counts.get("mca21", 0),
            total_gem=counts.get("gem", 0),
            total_msme=counts.get("msme", 0),
            total_government=total_gov,
            band_distribution=band_dist,
            by_state=by_state,
            by_sector=by_sector,
        )
    except Exception as exc:
        logger.error("government_stats_failed", error=str(exc))
        return GovStatsResponse(
            total_dpiit=0, total_mca21=0, total_gem=0, total_msme=0,
            total_government=0, band_distribution={}, by_state={}, by_sector={},
        )


@router.get("/apisetu/search", response_model=ApisetuSearchResponse)
async def apisetu_search(
    session: DbSession,
    user: CurrentUser,
    cin: str | None = Query(None, description="Corporate Identification Number (MCA21)"),
    gstin: str | None = Query(None, description="GST Identification Number"),
    udyam: str | None = Query(None, description="Udhyam Aadhaar Number"),
) -> ApisetuSearchResponse:
    """Search across API Setu government data sources.

    Queries MCA21 (by CIN), GST (by GSTIN), and/or Udyam (by Udhyam Aadhaar)
    via the API Setu gateway. At least one identifier must be provided.
    """
    if not any([cin, gstin, udyam]):
        raise HTTPException(
            status_code=400,
            detail="At least one of cin, gstin, or udyam must be provided",
        )

    from backend.collectors.apisetu_client import APISetuClient

    client = APISetuClient(api_key=getattr(settings, "APISETU_API_KEY", None))
    enriched = await client.enrich_company(cin=cin, gstin=gstin, udyam=udyam)

    results: list[ApisetuSearchResult] = []
    found_count = 0

    for source_name, raw_post in enriched.items():
        if raw_post is None:
            results.append(ApisetuSearchResult(
                source=source_name,
                status="not_found",
            ))
        else:
            found_count += 1
            results.append(ApisetuSearchResult(
                source=source_name,
                status="found",
                title=raw_post.title,
                external_id=raw_post.external_id,
                data=raw_post.raw_meta,
            ))

    logger.info(
        "apisetu_search_complete",
        cin=cin,
        gstin=gstin,
        udyam=udyam,
        found=found_count,
    )
    return ApisetuSearchResponse(results=results, total_found=found_count)


@router.get("/verify/{cin}", response_model=VerifyCompanyResponse)
async def verify_company(
    cin: str,
    session: DbSession,
    user: CurrentUser,
) -> VerifyCompanyResponse:
    """Cross-reference verify a company by Corporate Identification Number (CIN).

    Checks the CIN across DPIIT, MCA21, GeM, and MSME sources to determine
    which registries have data for the company.
    """
    verified_at = datetime.now(UTC).isoformat()
    try:
        # Look up CIN across all government sources
        result = await session.execute(
            select(Lead)
            .where(Lead.source.in_(GOVT_SOURCES))
            .where(Lead.company_name.ilike(f"%{cin}%"))
            .limit(10)
        )
        leads = list(result.scalars().all())

        company_name: str | None = None
        dpiit_status: str | None = None
        mca21_status: str | None = None
        gem_status: str | None = None
        msme_status: str | None = None

        for lead in leads:
            if not company_name and lead.company_name:
                company_name = lead.company_name
            if lead.source == "dpiit":
                dpiit_status = "found"
            elif lead.source == "mca21":
                mca21_status = "found"
            elif lead.source == "gem":
                gem_status = "found"
            elif lead.source == "msme":
                msme_status = "found"

        # If not found in DB, mark as not_found
        if not any([dpiit_status, mca21_status, gem_status, msme_status]):
            company_name = f"CIN: {cin}"

        return VerifyCompanyResponse(
            cin=cin,
            company_name=company_name,
            dpiit_status=dpiit_status or "not_found",
            mca21_status=mca21_status or "not_found",
            gem_status=gem_status or "not_found",
            msme_status=msme_status or "not_found",
            verified_at=verified_at,
        )
    except Exception as exc:
        logger.error("company_verification_failed", cin=cin, error=str(exc))
        return VerifyCompanyResponse(
            cin=cin,
            company_name=None,
            dpiit_status="error",
            mca21_status="error",
            gem_status="error",
            msme_status="error",
            verified_at=verified_at,
        )


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _gov_lead_to_out(lead: Lead) -> GovLeadOut:
    """Convert ORM Lead to GovLeadOut schema."""
    return GovLeadOut(
        id=str(lead.id),
        company_name=lead.company_name,
        industry=lead.industry,
        location=lead.location,
        company_size=lead.company_size,
        funding_stage=getattr(lead, "funding_stage", None),
        final_score=lead.final_score,
        score_band=lead.score_band,
        source=getattr(lead, "source", None),
        created_at=lead.created_at,
    )
