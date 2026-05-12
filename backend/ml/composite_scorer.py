"""
backend/ml/composite_scorer.py — Ensemble Scorer (GBM + LLM + RL + Uplift + Geo).

Based on:
    - VALOR (arXiv 2604.02472) — ensemble revenue prediction
    - Geo-DANN (ICLR 2026) — geographic fairness adjustment
    - Frontiers 2025 — GBM scoring engine

Weights are tuned via Optuna at training time. Default distribution:
    GBM:   0.30  (structured feature importance)
    LLM:   0.25  (qualitative context understanding)
    RL:    0.20  (sequential action optimization)
    Uplift: 0.15 (incremental revenue impact)
    Geo:   0.10  (location fairness / geographic bias correction)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

from backend.ml.geo_scorer import GeoFairnessScorer
from backend.ml.qualitative_scorer import LLMQualitativeScorer
from backend.ml.rl_scorer import RLSequentialScorer
from backend.ml.scoring_model import GradientBoostingScorer, LeadProtocol
from backend.ml.uplift_scorer import UpliftRevenueScorer

logger = structlog.get_logger()


# ── ScoringResult ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoringResult:
    """Immutable result dataclass for composite scoring.

    Attributes:
        final_score: Weighted composite score (0-100).
        band: Classification band (hot, warm, cool, cold).
        component_scores: Raw scores from each model before weighting.
        confidence: Model agreement confidence (0-1).
        recommended_action: Suggested next action.
        explanation: Human-readable explanation of the score.
    """

    final_score: float
    band: str
    component_scores: dict[str, float]
    confidence: float
    recommended_action: str
    explanation: str


# ── Band Definitions ──────────────────────────────────────────────────────────

BAND_THRESHOLDS: list[tuple[float, str, str]] = [
    (75.0, "hot", "immediate_outreach"),
    (50.0, "warm", "nurture_sequence"),
    (25.0, "cool", "long_term_nurture"),
    (0.0, "cold", "drip_campaign"),
]

DEFAULT_WEIGHTS: dict[str, float] = {
    "gbm": 0.30,
    "llm": 0.25,
    "rl": 0.20,
    "uplift": 0.15,
    "geo": 0.10,
}


# ── CompositeScorer ───────────────────────────────────────────────────────────


class CompositeScorer:
    """Ensemble scorer combining all research-backed methods.

    Runs all five scorers in parallel via ``asyncio.gather``, normalizes
    their outputs to 0-100, and computes a weighted composite score.

    Usage:
        scorer = CompositeScorer()
        result = await scorer.score(lead)
        print(result.final_score, result.band)
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.gbm = GradientBoostingScorer()
        self.llm = LLMQualitativeScorer()
        self.rl = RLSequentialScorer()
        self.uplift = UpliftRevenueScorer()
        self.geo = GeoFairnessScorer()

        self.weights: dict[str, float] = weights or DEFAULT_WEIGHTS

    async def score(self, lead: LeadProtocol) -> ScoringResult:
        """Compute composite score using all five models.

        Args:
            lead: The lead to score.

        Returns:
            A ``ScoringResult`` with the composite score, band, and
            per-model breakdown.
        """
        # Run all scorers in parallel
        results = await asyncio.gather(
            self._score_gbm(lead),
            self._score_llm(lead),
            self._score_rl(lead),
            self._score_uplift(lead),
            self._score_geo(lead),
            return_exceptions=True,
        )

        # Extract scores with error fallback
        gbm_score = results[0] if not isinstance(results[0], Exception) else 0.5
        llm_score = results[1] if not isinstance(results[1], Exception) else 50.0
        rl_score = results[2] if not isinstance(results[2], Exception) else 0.5
        uplift_score = results[3] if not isinstance(results[3], Exception) else 0.5
        geo_score = results[4] if not isinstance(results[4], Exception) else 0.5

        # Normalize all scores to 0-100 scale
        gbm_norm = float(max(0.0, min(gbm_score * 100.0, 100.0)))  # type: ignore[operator]
        llm_norm = float(max(0.0, min(llm_score, 100.0)))  # type: ignore[operator]  # Already 0-100
        rl_norm = float(max(0.0, min(rl_score * 100.0, 100.0)))  # type: ignore[operator]
        uplift_norm = float(max(0.0, min(uplift_score * 100.0, 100.0)))  # type: ignore[operator]
        geo_norm = float(max(0.0, min(geo_score * 100.0, 100.0)))  # type: ignore[operator]

        component_scores: dict[str, float] = {
            "gbm": gbm_norm,
            "llm": llm_norm,
            "rl": rl_norm,
            "uplift": uplift_norm,
            "geo": geo_norm,
        }

        # Weighted composite score
        final_score = (
            self.weights["gbm"] * gbm_norm
            + self.weights["llm"] * llm_norm
            + self.weights["rl"] * rl_norm
            + self.weights["uplift"] * uplift_norm
            + self.weights["geo"] * geo_norm
        )

        # Classify band
        band = self._classify_band(final_score)

        return ScoringResult(
            final_score=round(final_score, 2),
            band=band,
            component_scores=component_scores,
            confidence=self._compute_confidence(results),
            recommended_action=self._recommend_action(band),
            explanation=self._generate_explanation(lead, final_score),
        )

    # ── Individual Scorer Wrappers ──────────────────────────────────────

    async def _score_gbm(self, lead: LeadProtocol) -> float:
        return self.gbm.predict(lead)

    async def _score_llm(self, lead: LeadProtocol) -> float:
        result = await self.llm.analyze(lead)
        return float(result.get("qualitative_score", 50)) / 100.0

    async def _score_rl(self, lead: LeadProtocol) -> float:
        return self.rl.predict(lead)

    async def _score_uplift(self, lead: LeadProtocol) -> float:
        return self.uplift.compute(lead)

    async def _score_geo(self, lead: LeadProtocol) -> float:
        return self.geo.adjust(lead, getattr(lead, "location", None) or "")

    # ── Classification & Confidence ─────────────────────────────────────

    @staticmethod
    def _classify_band(score: float) -> str:
        """Classify a numeric score into a priority band.

        Args:
            score: Normalized score (0-100).

        Returns:
            One of 'hot', 'warm', 'cool', 'cold'.
        """
        for threshold, band, _ in BAND_THRESHOLDS:
            if score >= threshold:
                return band
        return "cold"

    @staticmethod
    def _compute_confidence(results: list[Any]) -> float:
        """Compute confidence based on model agreement (inverse variance).

        High agreement across models = high confidence.
        Uses coefficient of variation normalized to 0-1.

        Args:
            results: Raw results from all scorers (may include Exceptions).

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        scores = [r for r in results if isinstance(r, (int, float))]
        if len(scores) < 2:
            return 0.5

        variance = float(np.var(scores))
        # Scale: variance of 0 = confidence 1.0, variance of 0.25 = confidence 0.0
        confidence = 1.0 - min(variance * 4.0, 1.0)
        return round(confidence, 4)

    @staticmethod
    def _recommend_action(band: str) -> str:
        """Map a priority band to a recommended action."""
        action_map: dict[str, str] = {
            "hot": "immediate_outreach",
            "warm": "nurture_sequence",
            "cool": "long_term_nurture",
            "cold": "drip_campaign",
        }
        return action_map.get(band, "review")

    @staticmethod
    def _generate_explanation(lead: LeadProtocol, score: float) -> str:
        """Generate a brief human-readable explanation for the score."""
        source = getattr(lead, "source", "unknown")
        job_count = getattr(lead, "raw_meta", {}).get("job_count", 0)
        registered = bool(
            getattr(lead, "gst_number", None) or getattr(lead, "udyam_number", None),
        )
        return (
            f"Score {score:.1f} based on {source} signals, "
            f"{job_count} job postings, "
            f"government registration: {registered}"
        )
