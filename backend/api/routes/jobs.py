"""
api/routes/jobs.py — Job Platform API Routes.

Triggers collection from Naukri / Internshala / Shine / LinkedIn / Indeed and
queries leads by job-related filters (skills, experience, work_mode, location, band).

POST endpoints are rate-limited via slowapi.
"""
from __future__ import annotations

import structlog
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from backend.api.deps import CurrentUser, DbSession, StreamClient
from backend.events.emitter import emit
from backend.shared.config import settings
from backend.shared.models import Lead
from backend.shared.repository import LeadRepo

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Schemas ──────────────────────────────────────────────────────────────────────

class CollectJobRequest(BaseModel):
    """Request body for triggering job platform collection."""
    keywords: list[str] = Field(default_factory=list, description="Search keywords / skills")
    locations: list[str] = Field(default_factory=list, description="Target locations")
    max_results: int = Field(50, ge=1, le=500, description="Max results to collect")


class CollectJobResponse(BaseModel):
    """Response after triggering a job collection."""
    status: str
    job_id: str
    source: str
    message: str


class JobLeadOut(BaseModel):
    """Simplified lead output for job-sourced leads."""
    id: str
    company_name: str | None = None
    contact_title: str | None = None
    industry: str | None = None
    location: str | None = None
    final_score: float = 0.0
    score_band: str = "cold"
    source: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class JobLeadListResponse(BaseModel):
    """Paginated response for job lead queries."""
    total: int
    page: int
    page_size: int
    leads: list[JobLeadOut]


class JobStatsResponse(BaseModel):
    """Statistics for job platform leads."""
    total_naukri: int
    total_internshala: int
    total_shine: int
    total_linkedin: int
    total_indeed: int
    total_jobs: int
    band_distribution: dict[str, int]


JOB_STREAM: str = "lead:jobs_collected"

# ── Niche platform registry ─────────────────────────────────────────────────────

NICHE_PLATFORMS: dict[str, str] = {
    "monster": "Monster India",
    "naukrigulf": "NaukriGulf",
    "freshersworld": "Freshersworld",
    "hirist": "Hirist (Tech Jobs)",
    "cutshort": "CutShort",
    "instahyre": "Instahyre",
    "hirect": "Hirect",
    "weekday": "Weekday",
    "timesjobs": "TimesJobs",
    "foundit": "Foundit",
    "sarkari_result": "Sarkari Result",
    "freejobalert": "FreeJobAlert",
    "employment_news": "Employment News",
    "iimjobs": "IIMJobs",
}

ALL_JOB_SOURCES: list[str] = [
    "naukri", "internshala", "shine", "linkedin_jobs", "indeed",
    *NICHE_PLATFORMS,
]

# ── Collection Endpoints (rate-limited) ──────────────────────────────────────────


@router.post("/collect/naukri", response_model=CollectJobResponse, status_code=202)
async def collect_naukri(
    body: CollectJobRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectJobResponse:
    """Trigger Naukri job collection.

    Emits a collection request to the jobs stream.
    The actual scraping is handled by a background worker.
    """
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "naukri",
            "keywords": body.keywords,
            "locations": body.locations,
            "max_results": body.max_results,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(JOB_STREAM, payload)
        await emit("signal_detected", {
            "source": "naukri",
            "job_id": job_id,
            "keywords": body.keywords,
            "stream_event_id": event_id,
        })
        logger.info("naukri_collection_queued", job_id=job_id, keywords=body.keywords)
        return CollectJobResponse(
            status="queued",
            job_id=job_id,
            source="naukri",
            message=f"Naukri collection queued for keywords: {', '.join(body.keywords)}",
        )
    except Exception as exc:
        logger.error("naukri_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue collection") from exc


@router.post("/collect/shine", response_model=CollectJobResponse, status_code=202)
async def collect_shine(
    body: CollectJobRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectJobResponse:
    """Trigger Shine.com job collection."""
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "shine",
            "keywords": body.keywords,
            "locations": body.locations,
            "max_results": body.max_results,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(JOB_STREAM, payload)
        await emit("signal_detected", {
            "source": "shine",
            "job_id": job_id,
            "keywords": body.keywords,
            "stream_event_id": event_id,
        })
        logger.info("shine_collection_queued", job_id=job_id, keywords=body.keywords)
        return CollectJobResponse(
            status="queued",
            job_id=job_id,
            source="shine",
            message=f"Shine.com collection queued for keywords: {', '.join(body.keywords)}",
        )
    except Exception as exc:
        logger.error("shine_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue collection") from exc


@router.post("/collect/internshala", response_model=CollectJobResponse, status_code=202)
async def collect_internshala(
    body: CollectJobRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectJobResponse:
    """Trigger Internshala internship collection."""
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "internshala",
            "keywords": body.keywords,
            "locations": body.locations,
            "max_results": body.max_results,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(JOB_STREAM, payload)
        await emit("signal_detected", {
            "source": "internshala",
            "job_id": job_id,
            "categories": body.keywords,
            "stream_event_id": event_id,
        })
        logger.info("internshala_collection_queued", job_id=job_id)
        return CollectJobResponse(
            status="queued",
            job_id=job_id,
            source="internshala",
            message="Internshala collection queued",
        )
    except Exception as exc:
        logger.error("internshala_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue collection") from exc


@router.post("/collect/linkedin", response_model=CollectJobResponse, status_code=202)
async def collect_linkedin_jobs(
    body: CollectJobRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectJobResponse:
    """Trigger LinkedIn Jobs collection."""
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "linkedin_jobs",
            "keywords": body.keywords,
            "locations": body.locations,
            "max_results": body.max_results,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(JOB_STREAM, payload)
        await emit("signal_detected", {
            "source": "linkedin_jobs",
            "job_id": job_id,
            "keywords": body.keywords,
            "locations": body.locations,
            "stream_event_id": event_id,
        })
        logger.info("linkedin_jobs_collection_queued", job_id=job_id, keywords=body.keywords)
        return CollectJobResponse(
            status="queued",
            job_id=job_id,
            source="linkedin_jobs",
            message=f"LinkedIn Jobs collection queued for keywords: {', '.join(body.keywords)}",
        )
    except Exception as exc:
        logger.error("linkedin_jobs_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue collection") from exc


@router.post("/collect/indeed", response_model=CollectJobResponse, status_code=202)
async def collect_indeed(
    body: CollectJobRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectJobResponse:
    """Trigger Indeed India job collection."""
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": "indeed",
            "keywords": body.keywords,
            "locations": body.locations,
            "max_results": body.max_results,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(JOB_STREAM, payload)
        await emit("signal_detected", {
            "source": "indeed",
            "job_id": job_id,
            "keywords": body.keywords,
            "locations": body.locations,
            "stream_event_id": event_id,
        })
        logger.info("indeed_collection_queued", job_id=job_id, keywords=body.keywords)
        return CollectJobResponse(
            status="queued",
            job_id=job_id,
            source="indeed",
            message=f"Indeed India collection queued for keywords: {', '.join(body.keywords)}",
        )
    except Exception as exc:
        logger.error("indeed_collection_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue collection") from exc


# ── Niche Platform Collection ───────────────────────────────────────────────────


@router.post("/collect/{platform}", response_model=CollectJobResponse, status_code=202)
async def collect_niche_platform(
    platform: str,
    body: CollectJobRequest,
    stream: StreamClient,
    user: CurrentUser,
) -> CollectJobResponse:
    """Trigger collection from any registered niche platform."""
    if platform not in NICHE_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    display_name = NICHE_PLATFORMS[platform]
    job_id = str(uuid.uuid4())
    try:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "source": platform,
            "keywords": body.keywords,
            "locations": body.locations,
            "max_results": body.max_results,
            "triggered_by": user,
            "triggered_at": datetime.now(UTC).isoformat(),
        }
        event_id = await stream.publish(JOB_STREAM, payload)
        await emit("signal_detected", {
            "source": platform,
            "job_id": job_id,
            "keywords": body.keywords,
            "stream_event_id": event_id,
        })
        logger.info(
            "niche_collection_queued",
            platform=platform,
            job_id=job_id,
            keywords=body.keywords,
        )
        return CollectJobResponse(
            status="queued",
            job_id=job_id,
            source=platform,
            message=f"{display_name} collection queued for keywords: {', '.join(body.keywords)}",
        )
    except Exception as exc:
        logger.error("niche_collection_failed", platform=platform, error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to queue collection") from exc


# ── Query Endpoints ──────────────────────────────────────────────────────────────


@router.get("/naukri", response_model=JobLeadListResponse)
async def query_naukri_leads(
    session: DbSession,
    user: CurrentUser,
    skills: list[str] | None = Query(None, description="Filter by skills"),
    experience: str | None = Query(None, description="Experience level (e.g. 0-2, 3-5, 5+)"),
    work_mode: str | None = Query(None, description="remote / hybrid / on-site"),
    location: str | None = Query(None, description="Job location"),
    band: str | None = Query(None, description="Score band: hot / warm / cool / cold"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
) -> JobLeadListResponse:
    """Query Naukri-sourced leads with optional filters."""
    try:
        q = select(Lead).where(Lead.source == "naukri")

        if skills:
            q = q.where(Lead.tech_stack.op("&&")(skills))
        if experience:
            q = q.where(Lead.experience == experience)
        if work_mode:
            q = q.where(Lead.work_mode == work_mode)
        if location:
            q = q.where(Lead.location.ilike(f"%{location}%"))
        if band:
            q = q.where(Lead.score_band == band)

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(Lead.final_score.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        leads = list(result.scalars().all())

        return JobLeadListResponse(
            total=total,
            page=page,
            page_size=page_size,
            leads=[_job_lead_to_out(lead) for lead in leads],
        )
    except Exception as exc:
        logger.error("naukri_query_failed", error=str(exc))
        return JobLeadListResponse(total=0, page=page, page_size=page_size, leads=[])


@router.get("/internshala", response_model=JobLeadListResponse)
async def query_internshala_internships(
    session: DbSession,
    user: CurrentUser,
    skills: list[str] | None = Query(None, description="Filter by skills"),
    location: str | None = Query(None, description="Internship location"),
    band: str | None = Query(None, description="Score band"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> JobLeadListResponse:
    """Query Internshala-sourced internship leads."""
    try:
        q = select(Lead).where(Lead.source == "internshala")

        if skills:
            q = q.where(Lead.tech_stack.op("&&")(skills))
        if location:
            q = q.where(Lead.location.ilike(f"%{location}%"))
        if band:
            q = q.where(Lead.score_band == band)

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(Lead.final_score.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        leads = list(result.scalars().all())

        return JobLeadListResponse(
            total=total,
            page=page,
            page_size=page_size,
            leads=[_job_lead_to_out(lead) for lead in leads],
        )
    except Exception as exc:
        logger.error("internshala_query_failed", error=str(exc))
        return JobLeadListResponse(total=0, page=page, page_size=page_size, leads=[])


@router.get("/linkedin", response_model=JobLeadListResponse)
async def query_linkedin_jobs(
    session: DbSession,
    user: CurrentUser,
    skills: list[str] | None = Query(None, description="Filter by skills"),
    location: str | None = Query(None, description="Job location"),
    band: str | None = Query(None, description="Score band"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> JobLeadListResponse:
    """Query LinkedIn-sourced job leads."""
    try:
        q = select(Lead).where(Lead.source == "linkedin_jobs")

        if skills:
            q = q.where(Lead.tech_stack.op("&&")(skills))
        if location:
            q = q.where(Lead.location.ilike(f"%{location}%"))
        if band:
            q = q.where(Lead.score_band == band)

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(Lead.final_score.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        leads = list(result.scalars().all())

        return JobLeadListResponse(
            total=total,
            page=page,
            page_size=page_size,
            leads=[_job_lead_to_out(lead) for lead in leads],
        )
    except Exception as exc:
        logger.error("linkedin_query_failed", error=str(exc))
        return JobLeadListResponse(total=0, page=page, page_size=page_size, leads=[])


@router.get("/indeed", response_model=JobLeadListResponse)
async def query_indeed_jobs(
    session: DbSession,
    user: CurrentUser,
    skills: list[str] | None = Query(None, description="Filter by skills"),
    location: str | None = Query(None, description="Job location"),
    band: str | None = Query(None, description="Score band"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> JobLeadListResponse:
    """Query Indeed-sourced job leads."""
    try:
        q = select(Lead).where(Lead.source == "indeed")

        if skills:
            q = q.where(Lead.tech_stack.op("&&")(skills))
        if location:
            q = q.where(Lead.location.ilike(f"%{location}%"))
        if band:
            q = q.where(Lead.score_band == band)

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(Lead.final_score.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        leads = list(result.scalars().all())

        return JobLeadListResponse(
            total=total,
            page=page,
            page_size=page_size,
            leads=[_job_lead_to_out(lead) for lead in leads],
        )
    except Exception as exc:
        logger.error("indeed_query_failed", error=str(exc))
        return JobLeadListResponse(total=0, page=page, page_size=page_size, leads=[])


@router.get("/{platform}", response_model=JobLeadListResponse)
async def query_niche_platform(
    platform: str,
    session: DbSession,
    user: CurrentUser,
    skills: list[str] | None = Query(None, description="Filter by skills"),
    location: str | None = Query(None, description="Job location"),
    band: str | None = Query(None, description="Score band"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> JobLeadListResponse:
    """Query leads from any registered niche platform."""
    if platform not in NICHE_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    try:
        q = select(Lead).where(Lead.source == platform)

        if skills:
            q = q.where(Lead.tech_stack.op("&&")(skills))
        if location:
            q = q.where(Lead.location.ilike(f"%{location}%"))
        if band:
            q = q.where(Lead.score_band == band)

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        q = q.order_by(Lead.final_score.desc()).offset(offset).limit(page_size)
        result = await session.execute(q)
        leads = list(result.scalars().all())

        return JobLeadListResponse(
            total=total,
            page=page,
            page_size=page_size,
            leads=[_job_lead_to_out(lead) for lead in leads],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("niche_platform_query_failed", platform=platform, error=str(exc))
        return JobLeadListResponse(total=0, page=page, page_size=page_size, leads=[])


@router.get("/stats", response_model=JobStatsResponse)
async def job_platform_stats(
    session: DbSession,
    user: CurrentUser,
) -> JobStatsResponse:
    """Get job platform statistics — total counts per platform and band distribution."""
    try:
        naukri_result = await session.execute(
            select(func.count(Lead.id)).where(Lead.source == "naukri")
        )
        total_naukri = naukri_result.scalar() or 0

        internshala_result = await session.execute(
            select(func.count(Lead.id)).where(Lead.source == "internshala")
        )
        total_internshala = internshala_result.scalar() or 0

        shine_result = await session.execute(
            select(func.count(Lead.id)).where(Lead.source == "shine")
        )
        total_shine = shine_result.scalar() or 0

        linkedin_result = await session.execute(
            select(func.count(Lead.id)).where(Lead.source == "linkedin_jobs")
        )
        total_linkedin = linkedin_result.scalar() or 0

        indeed_result = await session.execute(
            select(func.count(Lead.id)).where(Lead.source == "indeed")
        )
        total_indeed = indeed_result.scalar() or 0

        all_sources = ALL_JOB_SOURCES
        band_result = await session.execute(
            select(Lead.score_band, func.count(Lead.id))
            .where(Lead.source.in_(all_sources))
            .group_by(Lead.score_band)
        )
        band_distribution: dict[str, int] = {"hot": 0, "warm": 0, "cool": 0, "cold": 0}
        for row in band_result:
            band_distribution[row[0]] = row[1]

        total_all = sum(r[1] for r in (await session.execute(
            select(Lead.score_band, func.count(Lead.id))
            .where(Lead.source.in_(ALL_JOB_SOURCES))
            .group_by(Lead.score_band)
        )).all()) if all_sources else 0

        return JobStatsResponse(
            total_naukri=total_naukri,
            total_internshala=total_internshala,
            total_shine=total_shine,
            total_linkedin=total_linkedin,
            total_indeed=total_indeed,
            total_jobs=total_all,
            band_distribution=band_distribution,
        )
    except Exception as exc:
        logger.error("job_stats_failed", error=str(exc))
        return JobStatsResponse(
            total_naukri=0,
            total_internshala=0,
            total_shine=0,
            total_linkedin=0,
            total_indeed=0,
            total_jobs=0,
            band_distribution={"hot": 0, "warm": 0, "cool": 0, "cold": 0},
        )


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _job_lead_to_out(lead: Lead) -> JobLeadOut:
    """Convert ORM Lead to JobLeadOut schema."""
    return JobLeadOut(
        id=str(lead.id),
        company_name=lead.company_name,
        contact_title=lead.contact_title,
        industry=lead.industry,
        location=lead.location,
        final_score=lead.final_score,
        score_band=lead.score_band,
        source=getattr(lead, "source", None),
        created_at=lead.created_at,
    )
