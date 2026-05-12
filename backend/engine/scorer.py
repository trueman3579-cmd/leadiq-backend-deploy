"""
engine/scorer.py — Multi-dimensional Lead Scoring Engine (v3)
Computes composite score from 12 intent signals + freshness + cross-source.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .intent_signals import EXTRACTORS, detect_source_reputation, calculate_freshness_multiplier


@dataclass
class LeadScore:
    overall: int = 0
    confidence: str = "UNKNOWN"
    dimensions: dict[str, int] = field(default_factory=dict)
    reasoning: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    recency_days: int = 0

    def classify(self) -> str:
        if self.overall >= 85:
            self.confidence = "HOT"
        elif self.overall >= 65:
            self.confidence = "WARM"
        elif self.overall >= 50:
            self.confidence = "COOL"
        else:
            self.confidence = "COLD"
        return self.confidence


class MultiDimensionalScorer:
    """12-signal intent scorer with cross-source validation."""

    # Weight multipliers: increase to make scoring hit higher bands
    DIM_WEIGHTS = {
        "pain_explicit": 25,  # Was: 15
        "hiring_intent": 20,  # Was: 12
        "tech_growth": 25,  # Was: 15
        "budget_signals": 25,  # Was: 18
        "user_growth": 18,  # Was: 10
        "champion_risk": 20,  # Was: 15
        "competitive_indicators": 18,  # Was: 10
        "urgency": 15,  # Was: 8
        "category_momentum": 10,  # Was: 5
        "community_sentiment": 10,  # Was: 5
        "decision_maker_present": 15,  # Was: 8
        "funding_runway": 18,  # Was: 10
        "engagement_depth": 15,  # Was: 7
        "source_reputation": 10,  # Was: 5
    }

    def score(self, text: str, sources: list[str], recency_days: int = 0) -> LeadScore:
        dims: dict[str, int] = {}
        weighted_sum = 0
        reasoning: list[str] = []

        for name, extractor in EXTRACTORS.items():
            dim_score, meta = extractor.score(text)
            dims[name] = dim_score
            weight = self.DIM_WEIGHTS.get(name, 0)
            weighted_sum += dim_score * weight
            if dim_score > 50 and meta:
                reasoning.append(f"{name}: {dim_score}/100 ({meta.get('hits', '?')} hits)")

        # Aggressive sqrt scaling:  sqrt(weighted_sum) * 2.5
        # Test: 1 weak signal (35pts × wt15) = 525 → sqrt(525) * 2.5 = 57 (COOL)
        # Test: 2 medium signals = 3000 → sqrt(3000) * 2.5 = 137 → clamped 100 (HOT)
        base_score = int(math.sqrt(max(weighted_sum, 1)) * 2.5)
        base_score = min(base_score, 100)

        # Source reputation boost (0-15 max)
        source_boost = sum(detect_source_reputation(src) * 0.1 for src in sources)
        source_boost = min(source_boost, 15)

        # Cross-source verification bonus (0-15 max)
        cross_source_bonus = min(len(set(sources)) * 3, 15)

        # Freshness multiplier (1.0 at day 0, 0.5 at day 7)
        freshness = calculate_freshness_multiplier(recency_days)

        # Final composite
        composite = min(int((base_score + source_boost + cross_source_bonus) * freshness), 100)

        score = LeadScore(
            overall=composite,
            dimensions=dims,
            reasoning=reasoning,
            sources=sources,
            recency_days=recency_days,
        )
        score.confidence = score.classify()
        return score
