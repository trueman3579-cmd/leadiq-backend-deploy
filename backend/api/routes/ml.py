"""
api/routes/ml.py — ML scoring endpoints (Phase 8).

POST /api/ml/score      → Score a lead with gradient boosting + SHAP
POST /api/ml/batch      → Batch score multiple leads
POST /api/ml/clv        → Predict customer lifetime value (BTYD)
GET  /api/ml/importance → Feature importance ranking
"""
from __future__ import annotations

import logging
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.ml_scorer import get_scorer, ScoreResult, CLVResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class ScoreRequest(BaseModel):
    lead: Dict[str, float] = Field(description="Lead features")

class ScoreResponse(BaseModel):
    score: float
    band: str
    confidence: float
    shap_values: Dict[str, float]
    explanation: str

class BatchScoreRequest(BaseModel):
    leads: List[Dict[str, float]]

class BatchScoreResponse(BaseModel):
    results: List[ScoreResponse]

class CLVRequest(BaseModel):
    frequency: int = Field(description="Number of repeat purchases")
    recency: float = Field(description="Days between first and last purchase")
    T: float = Field(description="Days since first purchase")
    monetary_value: float = Field(description="Average order value ($)")

class CLVResponse(BaseModel):
    expected_transactions: float
    expected_value: float
    clv_12_month: float
    probability_alive: float
    segment: str

class FeatureImportanceResponse(BaseModel):
    features: Dict[str, float]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/score", response_model=ScoreResponse)
async def score_lead(body: ScoreRequest):
    """
    Score a lead using gradient boosting with SHAP-style explanations.

    Returns score (0-100), band (hot/warm/cool/cold), confidence,
    and per-feature attribution.
    """
    scorer = get_scorer()
    result = scorer.score(body.lead)
    return _score_to_response(result)


@router.post("/batch", response_model=BatchScoreResponse)
async def batch_score(body: BatchScoreRequest):
    """Score multiple leads efficiently."""
    scorer = get_scorer()
    results = scorer.batch_score(body.leads)
    return BatchScoreResponse(results=[_score_to_response(r) for r in results])


@router.post("/clv", response_model=CLVResponse)
async def predict_clv(body: CLVRequest):
    """
    Predict 12-month Customer Lifetime Value using BG/NBD + Gamma-Gamma.

    Based on Fader & Hardie (2005) "Counting Your Customers the Easy Way".
    """
    scorer = get_scorer()
    result = scorer.btyd.predict_clv(
        frequency=body.frequency,
        recency=body.recency,
        T=body.T,
        monetary_value=body.monetary_value,
    )
    return _clv_to_response(result)


@router.get("/importance", response_model=FeatureImportanceResponse)
async def feature_importance():
    """Return feature importance from the trained gradient boosting model."""
    scorer = get_scorer()
    importance = scorer.gb.feature_importance()
    return FeatureImportanceResponse(features=importance)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _score_to_response(result: ScoreResult) -> ScoreResponse:
    return ScoreResponse(
        score=result.score,
        band=result.band,
        confidence=result.confidence,
        shap_values=result.shap_values,
        explanation=result.explanation,
    )


def _clv_to_response(result: CLVResult) -> CLVResponse:
    return CLVResponse(
        expected_transactions=result.expected_transactions,
        expected_value=result.expected_value,
        clv_12_month=result.clv_12_month,
        probability_alive=result.probability_alive,
        segment=result.segment,
    )
