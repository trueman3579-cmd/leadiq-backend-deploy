"""
api/routes/outreach.py — REST endpoint for RAG-powered outreach generation.

POST /api/outreach/rag → Generate personalized outreach with RAG context
GET  /api/outreach/templates → List saved templates
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.outreach_rag import OutreachRAG

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


# ── Request / Response schemas ──────────────────────────────────────────────

class GenerateOutreachRequest(BaseModel):
    company_id: str
    company_name: str
    product_description: str
    value_proposition: str
    user_query: str | None = None


class GenerateOutreachResponse(BaseModel):
    subject: str
    body: str
    personalization_score: int
    sources_used: list[str]
    confidence: str
    metadata: dict


# ── Service singleton ─────────────────────────────────────────────────────────

_outreach_service = None


def _get_service() -> OutreachRAG:
    global _outreach_service
    if _outreach_service is None:
        _outreach_service = OutreachRAG()
    return _outreach_service


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/rag", response_model=GenerateOutreachResponse)
async def generate_rag_outreach(body: GenerateOutreachRequest):
    """
    Generate personalized outreach using RAG context.

    Retrieves company facts from pgvector and grounds LLM generation
    in verified data sources.
    """
    service = _get_service()

    try:
        result = await service.generate_outreach(
            company_id=body.company_id,
            company_name=body.company_name,
            product_description=body.product_description,
            value_proposition=body.value_proposition,
            user_query=body.user_query,
        )

        return GenerateOutreachResponse(
            subject=result.get("subject", ""),
            body=result.get("body", ""),
            personalization_score=result.get("personalization_score", 0),
            sources_used=result.get("sources_used", []),
            confidence=result.get("confidence", "low"),
            metadata=result.get("metadata", {}),
        )
    except Exception as exc:
        logger.error(f"RAG outreach failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
async def outreach_health():
    """Health check for outreach service."""
    return {
        "status": "ok",
        "service": "outreach-rag",
        "rag_available": True,
        "llm_router_available": True,
    }
