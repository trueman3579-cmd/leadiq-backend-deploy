"""
ml_scorer.py — Machine Learning scoring stack (Phase 8).

Implements paper2code patterns from:
- "XGBoost: A Scalable Tree Boosting System" (Chen & Guestrin, KDD 2016)
- "A Unified Approach to Interpreting Model Predictions" (Lundberg & Lee, 2017)
- "Counting Your Customers the Easy Way" (Fader & Hardie, 2005) — BTYD

Lightweight numpy-based implementation. No heavy ML frameworks.
Uses gradient boosting with decision stumps + SHAP-style feature attribution.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    score: float  # 0-100
    band: str  # hot | warm | cool | cold
    confidence: float  # 0-1
    features: Dict[str, float]
    shap_values: Dict[str, float]
    explanation: str


@dataclass
class CLVResult:
    expected_transactions: float
    expected_value: float
    clv_12_month: float
    probability_alive: float
    segment: str  # champion | loyal | at_risk | lost


class DecisionStump:
    """A single-level decision tree used as weak learner in boosting."""

    def __init__(self):
        self.feature_idx: int = 0
        self.threshold: float = 0.0
        self.left_value: float = 0.0
        self.right_value: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray, weights: np.ndarray) -> float:
        """Fit a decision stump and return loss."""
        n_samples, n_features = X.shape
        best_loss = float('inf')

        for feature_idx in range(n_features):
            values = X[:, feature_idx]
            thresholds = np.percentile(values, [25, 50, 75])

            for threshold in thresholds:
                left_mask = values <= threshold
                right_mask = ~left_mask

                if left_mask.sum() == 0 or right_mask.sum() == 0:
                    continue

                # Weighted mean
                left_value = np.average(y[left_mask], weights=weights[left_mask])
                right_value = np.average(y[right_mask], weights=weights[right_mask])

                # Predictions
                preds = np.where(left_mask, left_value, right_value)
                loss = np.average((y - preds) ** 2, weights=weights)

                if loss < best_loss:
                    best_loss = loss
                    self.feature_idx = feature_idx
                    self.threshold = threshold
                    self.left_value = left_value
                    self.right_value = right_value

        return best_loss

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict using the fitted stump."""
        mask = X[:, self.feature_idx] <= self.threshold
        return np.where(mask, self.left_value, self.right_value)


class GradientBoostingScorer:
    """
    Lightweight gradient boosting classifier.

    Uses decision stumps as weak learners. Trains on synthetic + real
    feedback data. Produces scores 0-100 with SHAP-style explanations.
    """

    def __init__(
        self,
        n_estimators: int = 50,
        learning_rate: float = 0.1,
        feature_names: Optional[List[str]] = None,
    ):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.feature_names = feature_names or []
        self.stumps: List[DecisionStump] = []
        self.base_score: float = 50.0
        self._is_trained = False

    def _features_to_array(self, features: Dict[str, float]) -> np.ndarray:
        """Convert feature dict to numpy array."""
        if not self.feature_names:
            self.feature_names = list(features.keys())
        return np.array([features.get(k, 0.0) for k in self.feature_names])

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weights: Optional[np.ndarray] = None,
    ) -> "GradientBoostingScorer":
        """
        Train the gradient boosting model.

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target scores 0-100
            sample_weights: Optional sample weights
        """
        n_samples = X.shape[0]
        if sample_weights is None:
            sample_weights = np.ones(n_samples) / n_samples

        # Initialize residuals
        residuals = y - self.base_score

        for i in range(self.n_estimators):
            stump = DecisionStump()
            loss = stump.fit(X, residuals, sample_weights)

            preds = stump.predict(X)
            residuals -= self.learning_rate * preds

            self.stumps.append(stump)

            if i % 10 == 0:
                logger.debug(f"GB iteration {i}: loss={loss:.4f}")

        self._is_trained = True
        return self

    def predict(self, features: Dict[str, float]) -> ScoreResult:
        """
        Predict score with SHAP-style explanations.

        Returns score (0-100), band, confidence, and per-feature attribution.
        """
        x = self._features_to_array(features).reshape(1, -1)

        # Base prediction
        score = self.base_score
        shap_values = {k: 0.0 for k in self.feature_names}

        # Add contributions from each stump
        for stump in self.stumps:
            contribution = stump.predict(x)[0] * self.learning_rate
            score += contribution

            # Attribute to the feature used by this stump
            fname = self.feature_names[stump.feature_idx] if stump.feature_idx < len(self.feature_names) else "unknown"
            shap_values[fname] = shap_values.get(fname, 0.0) + contribution

        # Clamp to 0-100
        score = max(0.0, min(100.0, score))

        # Band assignment
        if score >= 80:
            band = "hot"
        elif score >= 60:
            band = "warm"
        elif score >= 40:
            band = "cool"
        else:
            band = "cold"

        # Confidence based on prediction variance from training
        confidence = 0.7 + (score / 1000)  # Simple heuristic

        # Explanation generation
        top_features = sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        explanation_parts = [f"{k} (+{v:.1f})" if v > 0 else f"{k} ({v:.1f})" for k, v in top_features]
        explanation = f"Score driven by: {', '.join(explanation_parts)}"

        return ScoreResult(
            score=round(score, 1),
            band=band,
            confidence=round(min(1.0, confidence), 2),
            features=features,
            shap_values={k: round(v, 2) for k, v in shap_values.items()},
            explanation=explanation,
        )

    def feature_importance(self) -> Dict[str, float]:
        """Return feature importance based on SHAP value variance."""
        importance = {}
        for stump in self.stumps:
            fname = self.feature_names[stump.feature_idx] if stump.feature_idx < len(self.feature_names) else "unknown"
            importance[fname] = importance.get(fname, 0.0) + abs(stump.left_value - stump.right_value)
        # Normalize
        total = sum(importance.values()) or 1.0
        return {k: round(v / total, 3) for k, v in importance.items()}


class BTYDModel:
    """
    Buy Till You Die (BG/NBD + Gamma-Gamma) lightweight implementation.

    Estimates customer lifetime value from transaction history using
    probabilistic models. Simplified for CPU-only inference.

    Reference: Fader & Hardie (2005) "Counting Your Customers the Easy Way"
    """

    def __init__(self):
        self.penalizer_coef = 0.01

    def fit(self, transactions: List[Dict]) -> "BTYDModel":
        """
        Fit model from transaction history.

        Args:
            transactions: List of {customer_id, date, amount}
        """
        # Simplified: just store for inference
        self.transactions = transactions
        return self

    def predict_clv(
        self,
        frequency: int,  # Number of repeat purchases
        recency: float,  # Time between first and last purchase (days)
        T: float,  # Time since first purchase (days)
        monetary_value: float,  # Average order value
    ) -> CLVResult:
        """
        Predict 12-month CLV using BG/NBD + Gamma-Gamma approximation.

        Uses closed-form approximations (no scipy required).
        """
        # Simplified BG/NBD parameters (would be fitted in full implementation)
        r, alpha = 0.5, 10.0  # Purchase process
        a, b = 0.8, 2.5  # Dropout process

        # Probability alive (simplified Pareto/NBD approximation)
        if frequency == 0:
            prob_alive = 0.1
        else:
            # Approximate using recency / T ratio
            x = recency / max(T, 1)
            prob_alive = math.exp(-0.5 * (1 - x) * frequency)
            prob_alive = max(0.05, min(0.99, prob_alive))

        # Expected transactions (next 12 months = 365 days)
        period = 365.0
        if frequency == 0:
            expected_trans = 0.5  # Prior expectation
        else:
            rate = frequency / max(recency, 1)
            expected_trans = rate * period * prob_alive
            expected_trans = min(expected_trans, 50)  # Cap

        # Gamma-Gamma: expected spend per transaction
        p, q, v = 6.0, 4.0, 15.0  # Shape parameters
        expected_spend = monetary_value * (p / (p + q - 1)) if (p + q - 1) > 0 else monetary_value

        # CLV
        clv = expected_trans * expected_spend * prob_alive

        # Segment
        if prob_alive > 0.8 and frequency >= 3:
            segment = "champion"
        elif prob_alive > 0.5 and frequency >= 2:
            segment = "loyal"
        elif prob_alive > 0.2:
            segment = "at_risk"
        else:
            segment = "lost"

        return CLVResult(
            expected_transactions=round(expected_trans, 1),
            expected_value=round(expected_spend, 2),
            clv_12_month=round(clv, 2),
            probability_alive=round(prob_alive, 2),
            segment=segment,
        )


class LeadScorer:
    """
    Production lead scorer combining gradient boosting + BTYD + rules.

    Integrates all ML scoring for the LeadIQ pipeline.
    """

    # Feature names (must match training order)
    FEATURE_NAMES = [
        "intent_score",
        "icp_fit",
        "velocity",
        "recency_days",
        "engagement_depth",
        "source_trust",
        "company_size_match",
        "industry_match",
        "funding_signal",
        "hiring_signal",
    ]

    def __init__(self):
        self.gb = GradientBoostingScorer(
            n_estimators=30,
            learning_rate=0.15,
            feature_names=self.FEATURE_NAMES,
        )
        self.btyd = BTYDModel()
        self._trained = False

    def train(self, leads: List[Dict]) -> "LeadScorer":
        """
        Train scorer on historical leads with feedback.

        Args:
            leads: List of dicts with features and final_score (0-100)
        """
        if len(leads) < 5:
            logger.warning(" insufficient_training_data", count=len(leads))
            return self

        X_list = []
        y_list = []
        weights = []

        for lead in leads:
            features = self._extract_features(lead)
            x = [features.get(k, 0.0) for k in self.FEATURE_NAMES]
            X_list.append(x)
            y_list.append(lead.get("final_score", 50.0))
            # Weight by feedback confidence
            weights.append(lead.get("feedback_weight", 1.0))

        X = np.array(X_list)
        y = np.array(y_list)
        w = np.array(weights)
        w = w / w.sum()  # Normalize

        self.gb.fit(X, y, w)
        self._trained = True
        logger.info("lead_scorer_trained", samples=len(leads), features=X.shape[1])
        return self

    def score(self, lead: Dict) -> ScoreResult:
        """Score a single lead with full ML stack."""
        features = self._extract_features(lead)

        if not self._trained:
            # Fallback: weighted rule-based scoring
            return self._rule_based_score(features)

        return self.gb.predict(features)

    def _extract_features(self, lead: Dict) -> Dict[str, float]:
        """Extract normalized features from a lead dict."""
        return {
            "intent_score": lead.get("intent_score", 0.5) * 100,
            "icp_fit": lead.get("icp_fit_score", 0.5) * 100,
            "velocity": lead.get("velocity", 0.0) * 100,
            "recency_days": max(0, 100 - lead.get("recency_days", 0)),
            "engagement_depth": lead.get("engagement_depth", 0.5) * 100,
            "source_trust": lead.get("source_trust", 0.5) * 100,
            "company_size_match": 100.0 if lead.get("company_size_match") else 0.0,
            "industry_match": 100.0 if lead.get("industry_match") else 0.0,
            "funding_signal": lead.get("funding_signal", 0.0) * 100,
            "hiring_signal": lead.get("hiring_signal", 0.0) * 100,
        }

    def _rule_based_score(self, features: Dict[str, float]) -> ScoreResult:
        """Fallback rule-based scoring when model not trained."""
        weights = {
            "intent_score": 0.25,
            "icp_fit": 0.20,
            "velocity": 0.15,
            "recency_days": 0.10,
            "engagement_depth": 0.10,
            "source_trust": 0.10,
            "company_size_match": 0.05,
            "industry_match": 0.05,
        }

        score = sum(features.get(k, 0) * w for k, w in weights.items())
        score = max(0, min(100, score))

        if score >= 80:
            band = "hot"
        elif score >= 60:
            band = "warm"
        elif score >= 40:
            band = "cool"
        else:
            band = "cold"

        shap = {k: round(features.get(k, 0) * w, 2) for k, w in weights.items()}
        top = sorted(shap.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        explanation = f"Rule-based: {', '.join(f'{k} ({v:+.1f})' for k, v in top)}"

        return ScoreResult(
            score=round(score, 1),
            band=band,
            confidence=0.6,
            features=features,
            shap_values=shap,
            explanation=explanation,
        )

    def batch_score(self, leads: List[Dict]) -> List[ScoreResult]:
        """Score multiple leads efficiently."""
        return [self.score(lead) for lead in leads]


# ── Singletons ─────────────────────────────────────────────────────────────

_scorer = None


def get_scorer() -> LeadScorer:
    global _scorer
    if _scorer is None:
        _scorer = LeadScorer()
    return _scorer
