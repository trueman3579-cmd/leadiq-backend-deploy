"""
backend/ml/uplift_scorer.py — Uplift Revenue Scorer (stub).

Based on: VALOR (arXiv 2604.02472).

VALOR uses uplift modeling to estimate the incremental revenue
impact of contacting a lead. Unlike traditional scoring, uplift
models answer: "How much more likely is this lead to convert if
contacted?" — enabling optimal treatment assignment.

Current implementation returns a baseline uplift of 0.5.
Replace with a trained causal forest / S-Learner / T-Learner model.

Reference: https://arxiv.org/abs/2604.02472
"""
from __future__ import annotations

import structlog

from backend.ml.scoring_model import LeadProtocol

logger = structlog.get_logger()


class UpliftRevenueScorer:
    """Uplift-based revenue impact scorer.

    Estimates the incremental conversion probability attributable
    to outreach (treatment effect). Higher scores mean the lead
    is more responsive to contact.

    Usage:
        scorer = UpliftRevenueScorer()
        uplift = scorer.compute(lead)
    """

    def __init__(self) -> None:
        self.model: object = None
        logger.info("uplift_scorer_initialized", mode="stub")

    def compute(self, lead: LeadProtocol) -> float:
        """Compute uplift score for a lead.

        Args:
            lead: The lead to evaluate.

        Returns:
            Uplift score between 0.0 and 1.0.
            Currently returns 0.5 baseline.
        """
        # TODO(ml): Replace with trained causal forest / S-Learner model
        logger.debug(
            "uplift_compute_stub",
            lead_id=getattr(lead, "id", None),
        )
        return 0.5
