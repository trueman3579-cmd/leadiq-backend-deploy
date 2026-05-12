"""
api/routes/scoring.py — Scoring API Routes.

Provides endpoints for scoring individual leads, batch scoring,
and explaining scoring decisions with feature importance breakdown.
"""
from __future__ import annotations

import structlog
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import CurrentUser, DbSession, StreamClient
from backend.events.emitter import emit
from backend.shared.models import Lead
from backend.shared.repository import LeadRepo
from backend.services.confidence import compute_confidence, explain_confidence
from backend.services.icp_service import calculate_icp_score

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


# ── Schemas ──────────────────────────────────────────────────────────────────────

class ScoreRequest(BaseModel):
    """Request to score a single lead."""
    lead_id: str = Field(..., description="UUID of the lead to score")


class ComponentScore(BaseModel):
    """Individual component of the composite score."""
    name: str
    value: float
    weight: float
    contribution: float


class ScoreResponse(BaseModel):
    """Composite score result for a single lead."""
    lead_id: str
    final_score: float
    score_band: str
    component_scores: list[ComponentScore]
    confidence: float
    scored_at: str


class BatchScoreRequest(BaseModel):
    """Request for batch scoring multiple leads."""
    lead_ids: list[str] = Field(..., min_length=1, max_length=100)
    force_recalculate: bool = Field(False, description="Re-score even if already scored")


class BatchScoreResult(BaseModel):
    """Individual result in a batch scoring response."""
    lead_id: str
    status: str
    final_score: float | None = None
    score_band: str | None = None
    error: str | None = None


class BatchScoreResponse(BaseModel):
    """Response from batch scoring."""
    total: int
    processed: int
    failed: int
    results: list[BatchScoreResult]


class FieldBreakdown(BaseModel):
    """Breakdown of a single field's contribution."""
    weight: float
    populated: bool
    contribution: float


class ScoreExplanation(BaseModel):
    """Detailed breakdown of what drove the score for a lead."""
    lead_id: str
    final_score: float
    score_band: str
    source: str
    source_trust: float
    field_completeness: float
    field_breakdown: dict[str, FieldBreakdown]
    icp_fit_score: float | None = None
    confidence: float


# ── Scoring Logic ────────────────────────────────────────────────────────────────

SCORE_BANDS: list[tuple[str, float, float]] = [
    ("hot", 80.0, 100.0),
    ("warm", 60.0, 79.99),
    ("cool", 40.0, 59.99),
    ("cold", 0.0, 39.99),
]


def _determine_band(final_score: float) -> str:
    """Map a numeric score to a band label."""
    for band, lo, hi in SCORE_BANDS:
        if lo <= final_score <= hi:
            return band
    return "cold"


def _compute_composite_score(lead: Lead) -> tuple[float, list[ComponentScore]]:
    """Compute composite score from multiple weighted components.

    Scoring components:
      1. Opportunity score (40%) — LLM-assessed buying signal strength
      2. ICP fit score (30%) — how well the lead matches the user's ICP
      3. Confidence (20%) — data quality / field completeness
      4. Intent signal bonus (10%) — detected intent signals (buy / evaluate / pain)
    """
    components: list[ComponentScore] = []

    # Component 1: Opportunity score (40%)
    opp_score = float(getattr(lead, "opportunity_score", 0.0) or 0.0)
    components.append(ComponentScore(
        name="opportunity_score",
        value=opp_score,
        weight=0.40,
        contribution=round(opp_score * 0.40, 2),
    ))

    # Component 2: ICP fit score (30%)
    icp_score = float(getattr(lead, "icp_fit_score", 0.0) or 0.0)
    components.append(ComponentScore(
        name="icp_fit_score",
        value=icp_score,
        weight=0.30,
        contribution=round(icp_score * 0.30, 2),
    ))

    # Component 3: Confidence (20%) — mapped to 0-100 scale
    confidence = float(getattr(lead, "confidence", 0.0) or 0.0)
    confidence_score = confidence * 100.0
    components.append(ComponentScore(
        name="confidence",
        value=confidence_score,
        weight=0.20,
        contribution=round(confidence_score * 0.20, 2),
    ))

    # Component 4: Intent signal bonus (10%)
    intent_map = {"buy": 90.0, "evaluate": 70.0, "pain": 60.0, "compare": 50.0}
    intent_raw = getattr(lead, "intent", None) or "other"
    intent_score = intent_map.get(intent_raw, 20.0)
    components.append(ComponentScore(
        name="intent_signals",
        value=intent_score,
        weight=0.10,
        contribution=round(intent_score * 0.10, 2),
    ))

    final_score = round(sum(c.contribution for c in components), 2)
    return final_score, components


# ── Endpoints ────────────────────────────────────────────────────────────────────


@router.post("/score", response_model=ScoreResponse)
async def score_lead(
    body: ScoreRequest,
    session: DbSession,
    stream: StreamClient,
    user: CurrentUser,
) -> ScoreResponse:
    """Score a single lead deterministically.

    Returns the composite score with all component scores for transparency.
    If the lead already has a final_score and force_recalculate is not set,
    returns the existing score.
    """
    try:
        repo = LeadRepo(session)
        lead = await repo.get(body.lead_id)

        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        final_score, components = _compute_composite_score(lead)
        score_band = _determine_band(final_score)
        confidence = float(getattr(lead, "confidence", 0.0) or 0.0)

        # Persist score back to the lead record
        source = getattr(lead, "source", "unknown")
        await repo.update_fields(body.lead_id, {
            "final_score": final_score,
            "score_band": score_band,
            "scored_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
        })

        await emit("lead_scored", {
            "id": body.lead_id,
            "final_score": final_score,
            "score_band": score_band,
            "confidence": confidence,
            "scored_by": user,
        })

        logger.info("lead_scored", lead_id=body.lead_id, final_score=final_score, band=score_band)

        return ScoreResponse(
            lead_id=body.lead_id,
            final_score=final_score,
            score_band=score_band,
            component_scores=components,
            confidence=confidence,
            scored_at=__import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("scoring_failed", lead_id=body.lead_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Scoring failed: {str(exc)}") from exc


@router.post("/batch", response_model=BatchScoreResponse)
async def batch_score_leads(
    body: BatchScoreRequest,
    session: DbSession,
    stream: StreamClient,
    user: CurrentUser,
) -> BatchScoreResponse:
    """Score multiple leads in batch.

    Optionally force-recalculate even if leads already have scores.
    Returns per-lead results with error tracking.
    """
    results: list[BatchScoreResult] = []
    processed = 0
    failed = 0

    for lead_id in body.lead_ids:
        try:
            repo = LeadRepo(session)
            lead = await repo.get(lead_id)

            if not lead:
                results.append(BatchScoreResult(
                    lead_id=lead_id,
                    status="not_found",
                    error="Lead not found",
                ))
                failed += 1
                continue

            # Skip if already scored and not force-recalculating
            existing_score = float(getattr(lead, "final_score", 0.0) or 0.0)
            if existing_score > 0.0 and not body.force_recalculate:
                results.append(BatchScoreResult(
                    lead_id=lead_id,
                    status="skipped",
                    final_score=existing_score,
                    score_band=getattr(lead, "score_band", "cold"),
                ))
                continue

            final_score, _ = _compute_composite_score(lead)
            score_band = _determine_band(final_score)

            await repo.update_fields(lead_id, {
                "final_score": final_score,
                "score_band": score_band,
                "scored_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            })

            results.append(BatchScoreResult(
                lead_id=lead_id,
                status="scored",
                final_score=final_score,
                score_band=score_band,
            ))
            processed += 1

        except Exception as exc:
            logger.error("batch_scoring_item_failed", lead_id=lead_id, error=str(exc))
            results.append(BatchScoreResult(
                lead_id=lead_id,
                status="error",
                error=str(exc),
            ))
            failed += 1

    await emit("lead_scored", {
        "batch": True,
        "total": len(body.lead_ids),
        "processed": processed,
        "failed": failed,
        "scored_by": user,
    })

    logger.info("batch_scoring_complete", total=len(body.lead_ids), processed=processed, failed=failed)

    return BatchScoreResponse(
        total=len(body.lead_ids),
        processed=processed,
        failed=failed,
        results=results,
    )


@router.get("/explain/{lead_id}", response_model=ScoreExplanation)
async def explain_score(
    lead_id: str,
    session: DbSession,
    user: CurrentUser,
) -> ScoreExplanation:
    """Get a detailed breakdown of what drove the score for a lead.

    Returns field-level importance, source trust, and ICP fit score
    to provide full transparency into the scoring decision.
    """
    try:
        repo = LeadRepo(session)
        lead = await repo.get(lead_id)

        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        source = getattr(lead, "source", "unknown")
        lead_dict = {
            "email": getattr(lead, "email", None),
            "linkedin_url": getattr(lead, "linkedin_url", None),
            "company_domain": getattr(lead, "company_domain", None),
            "title": getattr(lead, "contact_title", None),
            "tech_stack": getattr(lead, "tech_stack", []),
            "company_size": getattr(lead, "company_size", None),
            "intent_signals": getattr(lead, "intent_signals", []),
        }

        explanation = explain_confidence(lead_dict, source)

        field_breakdown: dict[str, FieldBreakdown] = {}
        for field_name, fb in explanation.get("field_breakdown", {}).items():
            field_breakdown[field_name] = FieldBreakdown(
                weight=fb["weight"],
                populated=fb["populated"],
                contribution=fb["contribution"],
            )

        return ScoreExplanation(
            lead_id=lead_id,
            final_score=float(lead.final_score),
            score_band=str(lead.score_band),
            source=source,
            source_trust=explanation["source_trust"],
            field_completeness=explanation["field_completeness"],
            field_breakdown=field_breakdown,
            icp_fit_score=float(getattr(lead, "icp_fit_score", 0.0) or 0.0),
            confidence=explanation["final_confidence"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("score_explanation_failed", lead_id=lead_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Explanation failed: {str(exc)}") from exc
