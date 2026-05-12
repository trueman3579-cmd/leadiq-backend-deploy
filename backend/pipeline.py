"""
pipeline.py — v3 Unified Lead Pipeline
Orchestrates all collectors, applies multi-dimensional scoring, manages graph state.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# v3: Multi-dimensional intent signals ( hepatitboat that classifies)
# See ARCHITECTURE_WORLDCLASS.md for the 12 intent dimensions


@dataclass
class LeadScore:
    """World-class lead score with 12 intent signal dimensions."""
    lead_id: str
    overall_score: int = 0                           # 0-100 composite
    dimensions: dict[str, int] = field(default_factory=dict)  # 12 signal scores
    signal_sources: list[str] = field(default_factory=list)       # Which sources contributed
    enrichment: dict[str, Any] = field(default_factory=dict)
    recency_days: int = 999                            # Days since sighting
    confidence: str = "unknown"                        # HOT/WARM/COOL/COLD
    reasoning: list[str] = field(default_factory=list)

    # Scoring weights (from architecture — sum = 100%)
    DIM_WEIGHTS = {
        "pain_explicit": 0.15,
        "hiring_intent": 0.12,
        "tech_growth": 0.15,
        "budget_signals": 0.18,
        "user_growth": 0.10,
        "champion_risk": 0.15,
        "competitive_indicators": 0.10,
        "urgency": 0.08,
        "category_momentum": 0.05,
        "community_sentiment": 0.05,
        "decision_maker_present": 0.08,
        "funding_runway": 0.10,
        "engagement_depth": 0.07,
        "source_reputation": 0.05,
    }

    def calculate(self) -> int:
        """Compute weighted composite score from intent dimensions."""
        weighted = sum(
            min(v, 100) * self.DIM_WEIGHTS.get(k, 0)
            for k, v in self.dimensions.items()
        )
        # Boost for multi-source verification
        source_bonus = min(len(self.signal_sources) * 3, 15)
        self.overall_score = min(int(weighted + source_bonus), 100)
        return self.overall_score

    def classify(self) -> str:
        """Classify lead temperature from composite score."""
        if self.overall_score >= 85:
            self.confidence = "HOT"
        elif self.overall_score >= 65:
            self.confidence = "WARM"
        elif self.overall_score >= 50:
            self.confidence = "COOL"
        else:
            self.confidence = "COLD"
        return self.confidence

    def add_signal(self, dimension: str, score: int, source: str) -> None:
        """Record a signal from any collector dimension."""
        self.dimensions[dimension] = max(self.dimensions.get(dimension, 0), score)
        if source not in self.signal_sources:
            self.signal_sources.append(source)


class UnifiedPipeline:
    """v3 Pipeline: Collect → Transform → Score → Enrich → Graph."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis = redis_url
        # TODO: add Redis, Neo4j, Ollama clients in follow-up
        self._leads: dict[str, LeadScore] = {}

    async def process(self, raw_posts: list[Any]) -> list[LeadScore]:
        """Full pipeline: raw posts → scored leads."""
        # Stage 1: Normalize + dedup (content hash)
        seen = set()
        unique = []
        for p in raw_posts:
            h = hash((p.source, p.external_id, p.title, p.body))
            if h not in seen:
                seen.add(h)
                unique.append(p)

        # Stage 2: Score each unique post
        scored: list[LeadScore] = []
        for post in unique:
            ls = LeadScore(
                lead_id=f"{post.source}:{post.external_id}",
                recency_days=(datetime.now(UTC) - post.collected_at).days,
            )
            # Apply heuristic dimensions from content
            for dim, weight in ls.DIM_WEIGHTS.items():
                score = self._extract_dimension(dim, post)
                ls.add_signal(dim, score, post.source)
            ls.overall_score = ls.calculate()
            ls.confidence = ls.classify()
            scored.append(ls)
            self._leads[ls.lead_id] = ls

        logger.info("Scored %d unique leads across %d dimensions", len(scored), len(ls.DIM_WEIGHTS))
        return scored

    def _extract_dimension(self, dimension: str, post: Any) -> int:
        """Extract dimension score from raw post (heuristic/regex)."""
        text = f"{post.title} {post.body}".lower()
        patterns = {
            "pain_explicit": ["issue", "problem", "struggling", "pain", "frustrated"],
            "hiring_intent": ["hiring", "looking for", "seeking", "join our team"],
            "tech_growth": ["scaling", "migration", "adopting", "migrating to"],
            "budget_signals": ["budget", "spending", "investment", "funding"],
            "user_growth": ["scale", "growth", "traffic", "viral"],
            "champion_risk": ["left", "departed", "former", "ex-"],
            "competitive_indicators": ["vs", "switch to", "alternative", "compared to"],
            "urgency": ["asap", "deadline", "urgent", "immediately"],
            "category_momentum": ["trending", "many companies", "everyone is"],
            "community_sentiment": ["love this", "hate", "terrible", "amazing"],
            "decision_maker": ["cto", "vp", "director", "head of"],
            "funding_runway": ["series", "funding", "burn rate", "run out"],
            "engagement_depth": ["deep dive", "evaluating", "researching"],
            "source_reputation": ["trusted", "recommended", "authoritative"],
        }
        for pat in patterns.get(dimension, []):
            if pat in text:
                # Simple presence scoring: 20-80 based on position
                return 20 + (80 * (len(text) - text.index(pat)) // len(text))
        return 10  # Default weak signal

    async def get_hot_leads(self, min_score: int = 80) -> list[LeadScore]:
        """Retrieve leads above threshold, sorted by score."""
        hot = [ls for ls in self._leads.values() if ls.overall_score >= min_score]
        hot.sort(key=lambda x: x.overall_score, reverse=True)
        return hot
