"""
backend/ml/rl_scorer.py — RL Sequential Scorer (stub).

Based on: SalesRLAgent (arXiv 2503.23303).

SalesRLAgent models lead outreach as a sequential decision-making
process where an RL agent learns optimal actions (email, call, wait)
based on lead state. The policy optimizes long-term conversion
probability rather than one-shot score.

Current implementation returns a baseline score of 0.5.
Replace with a trained PPO/DQN model for production.

Reference: https://arxiv.org/abs/2503.23303
"""
from __future__ import annotations

import structlog

from backend.ml.scoring_model import LeadProtocol

logger = structlog.get_logger()


class RLSequentialScorer:
    """Reinforcement Learning-based sequential lead scorer.

    In production, this class wraps a trained PPO agent that outputs
    both a conversion probability (value head) and an optimal action
    (policy head) given the current lead state.

    Usage:
        scorer = RLSequentialScorer()
        prob = scorer.predict(lead)
    """

    def __init__(self) -> None:
        self.model: object = None
        logger.info("rl_scorer_initialized", mode="stub")

    def predict(self, lead: LeadProtocol) -> float:
        """Predict sequential conversion probability.

        Args:
            lead: The lead to evaluate.

        Returns:
            Conversion probability between 0.0 and 1.0.
            Currently returns 0.5 baseline.
        """
        # TODO(ml): Replace with trained PPO/DQN agent from SalesRLAgent
        logger.debug(
            "rl_predict_stub",
            lead_id=getattr(lead, "id", None),
        )
        return 0.5
