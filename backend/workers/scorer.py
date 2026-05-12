"""
workers/scorer.py — OpportunityScorer (pure function — no DB, no Redis).

Scoring v2 — three-layer model:

  Layer 1 — Base score (0-100), unchanged from v1:
    final_score = 0.30 * opportunity_score
                + 0.25 * icp_fit_score
                + 0.20 * urgency_score
                + 0.15 * confidence
                + 0.10 * engagement_score

  Layer 2 — Temporal decay bonus:
    Fresh signal (today)   → +10 pts
    Week-old signal        →   0 pts
    Month-old signal       →  -8 pts (floored at -10)

  Layer 3 — Profile personalisation (computed on-demand in /api/profile/leads):
    Profile fit, keyword boost, feedback learning — computed at query time
    so the base final_score in DB is always the objective signal quality.

Score-band thresholds (applied to base score):
  ≥ 80 → hot
  ≥ 60 → warm
  ≥ 40 → cool
  <  40 → cold
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from backend.shared.config import settings
from backend.shared.stream import redis_stream

logger = logging.getLogger(__name__)


@dataclass
class ScoringInput:
    """All inputs for the scoring function. All floats are 0.0–1.0 unless noted."""
    is_opportunity: bool
    confidence: float           # from Gemini classifier
    intent: str                 # buy | evaluate | pain | compare | other (or mode-specific)
    urgency: str                # high | medium | low
    icp_fit_score: float        # from Gemini enrichment, 0–100 (normalized internally)
    engagement: float = 0.5     # upvotes / score normalized to 0–1
    collected_at: str = ""      # ISO timestamp — used for temporal decay bonus


@dataclass
class ScoringResult:
    opportunity_score: float    # 0–100
    icp_fit_score: float        # 0–100
    final_score: float          # 0–100  (base quality, without personalisation)
    score_band: str             # hot | warm | cool | cold


_INTENT_WEIGHTS: dict[str, float] = {
    # B2B sales
    "buy":      1.00,
    "evaluate": 0.75,
    "pain":     0.65,
    "compare":  0.55,
    "other":    0.20,
    # Hiring
    "hiring_urgent":  1.00,
    "company_growth": 0.70,
    "hiring_planned": 0.60,
    # Job search
    "open_role":           1.00,
    "compensation_signal": 0.80,
    "company_signal":      0.65,
    "culture_signal":      0.55,
    # Opportunity
    "market_gap":   1.00,
    "pain_point":   0.80,
    "trend":        0.65,
    "emerging_tech": 0.60,
}

_URGENCY_WEIGHTS: dict[str, float] = {
    "high":   1.00,
    "medium": 0.60,
    "low":    0.30,
}


def score_opportunity(inp: ScoringInput) -> ScoringResult:
    """
    Deterministic, side-effect-free scoring.
    Produces base quality score — personalisation applied separately at query time.
    """
    if not inp.is_opportunity:
        return ScoringResult(0.0, 0.0, 0.0, "cold")

    intent_w  = _INTENT_WEIGHTS.get(inp.intent, 0.2)
    urgency_w = _URGENCY_WEIGHTS.get(inp.urgency, 0.3)
    icp_norm  = min(max(inp.icp_fit_score / 100.0, 0.0), 1.0)

    opportunity_score = round(intent_w * 100, 1)
    icp_fit           = round(icp_norm * 100, 1)

    base_raw = (
        0.30 * intent_w
        + 0.25 * icp_norm
        + 0.20 * urgency_w
        + 0.15 * inp.confidence
        + 0.10 * min(max(inp.engagement, 0.0), 1.0)
    )
    base_score = round(base_raw * 100, 1)

    # Temporal decay bonus (additive, not multiplicative — preserves DB interpretability)
    temporal_bonus = 0.0
    if inp.collected_at:
        from backend.services.personalization import compute_temporal_decay
        decay          = compute_temporal_decay(inp.collected_at)
        temporal_bonus = round((decay - 0.50) * 20.0, 1)  # range [-8, +10]

    final_score = max(0.0, min(100.0, base_score + temporal_bonus))
    final_score = round(final_score, 1)

    if final_score >= 80:
        score_band = "hot"
    elif final_score >= 60:
        score_band = "warm"
    elif final_score >= 40:
        score_band = "cool"
    else:
        score_band = "cold"

    return ScoringResult(
        opportunity_score=opportunity_score,
        icp_fit_score=icp_fit,
        final_score=final_score,
        score_band=score_band,
    )


async def run_scorer(consumer_name: str = "scorer-1") -> None:
    """
    Consume lead:analyzed stream, score each, publish to lead:scored.
    """
    group = "scorers"
    stream = settings.STREAM_ANALYZED

    await redis_stream.ensure_group(stream, group)
    logger.info("Scorer consumer '%s' started, reading from '%s'", consumer_name, stream)

    while True:
        events = await redis_stream.consume_group(stream, group, consumer_name, count=10)
        for event in events:
            try:
                inp = ScoringInput(
                    is_opportunity=bool(event.get("is_opportunity", False)),
                    confidence=float(event.get("confidence", 0.0)),
                    intent=str(event.get("intent", "other")),
                    urgency=str(event.get("urgency", "low")),
                    icp_fit_score=float(event.get("icp_fit_score", 0.0)),
                    engagement=min(int(event.get("score", 0)) / 100.0, 1.0),
                    collected_at=str(event.get("collected_at", "")),
                )
                result = score_opportunity(inp)

                payload = {
                    **event.data,
                    "opportunity_score": result.opportunity_score,
                    "icp_fit_score": result.icp_fit_score,
                    "final_score": result.final_score,
                    "score_band": result.score_band,
                }
                await redis_stream.publish(settings.STREAM_SCORED, payload)
                await redis_stream.ack(stream, group, event.event_id)
                logger.info(
                    "Scored event %s: final_score=%.1f score_band=%s",
                    event.event_id, result.final_score, result.score_band,
                )
                # Emit domain event
                from backend.events.emitter import emit
                lead_id = event.get("id", str(uuid.uuid4()))
                await emit("lead_scored", {
                    "id": lead_id,
                    "final_score": result.final_score,
                    "score_band": result.score_band,
                })
            except Exception as exc:
                logger.error("Scorer failed on event %s: %s", event.event_id, exc)
