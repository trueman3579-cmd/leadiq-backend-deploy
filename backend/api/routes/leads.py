"""
api/routes/leads.py — Lead CRUD and pipeline trigger endpoints.

GET  /api/leads              → list all leads with filtering
PATCH /api/lead/{id}         → update stage / priority / notes
POST /api/run-miner          → trigger collection Celery task
POST /api/run-ai             → trigger analysis Celery task
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.security import HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from backend.api.deps import CurrentUser
from backend.api.schemas import (
    LeadListResponse,
    LeadOut,
    LeadUpdateRequest,
    LeadUpdateResponse,
    TriggerResponse,
)
from backend.services.pipeline_service import trigger_collection, trigger_analysis
from backend.shared.db import AsyncSessionLocal
from backend.shared.repository import LeadRepo

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api", tags=["leads"])


@router.get("/leads", response_model=LeadListResponse)
async def list_leads(
    user: CurrentUser,
    stage: str | None = Query(None),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> LeadListResponse:
    """List all leads with filtering. Falls back to empty list if database unavailable."""
    session: AsyncSessionLocal | None = None
    try:
        session = AsyncSessionLocal()
        async with session:
            repo = LeadRepo(session)
            leads = await repo.list_all(stage=stage, min_score=min_score, limit=limit, offset=offset)
            return LeadListResponse(
                leads=[LeadOut.model_validate(lead) for lead in leads],
                total=len(leads),
                page=offset // limit + 1,
                page_size=limit,
            )
    except SQLAlchemyError as exc:
        logger.warning("Database error in list_leads: %s", exc)
        return LeadListResponse(
            leads=[],
            total=0,
            page=1,
            page_size=limit,
        )
    except Exception as exc:
        logger.error("Unexpected error in list_leads: %s", exc)
        return LeadListResponse(
            leads=[],
            total=0,
            page=1,
            page_size=limit,
        )
    finally:
        if session:
            await session.close()


@router.patch("/lead/{lead_id}", response_model=LeadUpdateResponse)
async def update_lead(
    lead_id: str,
    body: LeadUpdateRequest,
    user: CurrentUser,
) -> LeadUpdateResponse:
    session: AsyncSessionLocal | None = None
    try:
        session = AsyncSessionLocal()
        async with session:
            repo = LeadRepo(session)
            updates = body.model_dump(exclude_none=True)
            if not updates:
                raise HTTPException(status_code=422, detail="No fields to update")
            lead = await repo.update_fields(lead_id, updates)
            if lead is None:
                raise HTTPException(status_code=404, detail="Lead not found")
            return LeadUpdateResponse(lead=LeadOut.model_validate(lead))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc
    finally:
        if session:
            await session.close()


@router.post("/run-miner", response_model=TriggerResponse)
async def trigger_miner(
    user: CurrentUser,
) -> TriggerResponse:
    """Trigger lead collection pipeline. Requires authentication."""
    return await trigger_collection()


@router.post("/run-ai", response_model=TriggerResponse)
async def trigger_ai(
    user: CurrentUser,
) -> TriggerResponse:
    """Trigger AI analysis pipeline. Requires authentication."""
    return await trigger_analysis()
