"""Tests for ML scorer service (Phase 8)."""

import pytest
import numpy as np
from backend.services.ml_scorer import (
    DecisionStump,
    GradientBoostingScorer,
    BTYDModel,
    LeadScorer,
    ScoreResult,
    CLVResult,
)


class TestDecisionStump:
    def test_fit_predict(self):
        X = np.array([[1.0], [2.0], [3.0], [4.0], [5.0]])
        y = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        weights = np.ones(5) / 5

        stump = DecisionStump()
        loss = stump.fit(X, y, weights)
        preds = stump.predict(X)
        assert loss >= 0
        assert len(preds) == 5


class TestGradientBoostingScorer:
    def test_train_and_predict(self):
        scorer = GradientBoostingScorer(
            n_estimators=10,
            learning_rate=0.1,
            feature_names=["a", "b"],
        )
        X = np.array([[1, 2], [2, 3], [3, 4], [4, 5], [5, 6]])
        y = np.array([50, 60, 70, 80, 90])
        scorer.fit(X, y)

        result = scorer.predict({"a": 3.0, "b": 4.0})
        assert isinstance(result, ScoreResult)
        assert 0 <= result.score <= 100
        assert result.band in ("hot", "warm", "cool", "cold")
        assert len(result.shap_values) == 2
        assert result.explanation

    def test_feature_importance(self):
        scorer = GradientBoostingScorer(
            n_estimators=50,
            feature_names=["x", "y"],
        )
        # Make both features matter equally
        rng = np.random.RandomState(42)
        X = rng.randn(50, 2)
        y = X[:, 0] * 25 + X[:, 1] * 25 + 50
        scorer.fit(X, y)

        importance = scorer.feature_importance()
        assert "x" in importance
        assert "y" in importance
        # Both should be > 0 and sum to 1
        assert importance["x"] > 0
        assert importance["y"] > 0
        total = sum(importance.values())
        assert abs(total - 1.0) < 0.01


class TestBTYDModel:
    def test_predict_clv_high_value(self):
        model = BTYDModel()
        result = model.predict_clv(
            frequency=10,
            recency=180.0,
            T=365.0,
            monetary_value=100.0,
        )
        assert isinstance(result, CLVResult)
        assert result.expected_transactions > 0
        assert result.expected_value > 0
        assert result.clv_12_month > 0
        assert result.probability_alive > 0
        assert result.segment in ("champion", "loyal", "at_risk", "lost")

    def test_predict_clv_new_customer(self):
        model = BTYDModel()
        result = model.predict_clv(
            frequency=0,
            recency=0.0,
            T=30.0,
            monetary_value=50.0,
        )
        assert result.segment in ("at_risk", "lost")
        assert result.probability_alive <= 0.5


class TestLeadScorer:
    def test_rule_based_score(self):
        scorer = LeadScorer()
        lead = {
            "intent_score": 0.8,
            "icp_fit_score": 0.7,
            "velocity": 0.6,
            "recency_days": 5,
            "engagement_depth": 0.5,
            "source_trust": 0.9,
            "company_size_match": True,
            "industry_match": True,
            "funding_signal": 0.5,
            "hiring_signal": 0.3,
        }
        result = scorer.score(lead)
        assert isinstance(result, ScoreResult)
        assert 0 <= result.score <= 100
        assert result.band in ("hot", "warm", "cool", "cold")

    def test_batch_score(self):
        scorer = LeadScorer()
        leads = [
            {"intent_score": 0.9, "icp_fit_score": 0.8},
            {"intent_score": 0.3, "icp_fit_score": 0.2},
        ]
        results = scorer.batch_score(leads)
        assert len(results) == 2
        assert results[0].score >= results[1].score
