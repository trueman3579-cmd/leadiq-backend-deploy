"""
backend/ml/feature_engineering.py — Feature Engineering Pipeline.

Transforms raw lead data into ML-ready feature vectors covering:
  - Temporal features (recency, velocity, acceleration)
  - Source quality tiers
  - Engagement velocity and acceleration
  - Company signals (age, growth rate, hiring momentum)
  - Market signals (industry momentum, competitive intensity)
  - Intent recency and frequency
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import structlog

from backend.ml.scoring_model import LeadProtocol

logger = structlog.get_logger()


# ── Industry Momentum Multipliers ─────────────────────────────────────────────

INDUSTRY_MOMENTUM: dict[str, float] = {
    "ai_ml": 1.0,
    "ai/ml": 1.0,
    "artificial intelligence": 1.0,
    "machine learning": 1.0,
    "fintech": 0.9,
    "healthtech": 0.9,
    "healthcare": 0.8,
    "saas": 0.8,
    "software as a service": 0.8,
    "ecommerce": 0.7,
    "e-commerce": 0.7,
    "edtech": 0.7,
    "education technology": 0.7,
}

COMPETITIVE_LOCATIONS: list[str] = [
    "bangalore",
    "bengaluru",
    "hyderabad",
    "pune",
    "chennai",
    "mumbai",
]

COMPETITIVE_INDUSTRIES: list[str] = [
    "ai_ml",
    "ai/ml",
    "fintech",
    "saas",
    "software",
]

SOURCE_TIERS: dict[str, int] = {
    "naukri": 3,
    "internshala": 3,
    "linkedin": 3,
    "dpiit": 3,
    "mca21": 3,
    "gem": 3,
    "reddit": 2,
    "hn": 2,
    "hacker_news": 2,
    "github": 2,
    "twitter": 1,
    "producthunt": 2,
    "yourstory": 3,
    "tracxn": 3,
    "indimart": 2,
}


# ── FeatureEngineer ────────────────────────────────────────────────────────────


class FeatureEngineer:
    """Engineer feature vectors from lead data.

    Transforms a single lead into a ``pd.Series`` of derived features
    that capture temporal dynamics, engagement trends, and market context.
    """

    def __init__(self) -> None:
        self.scaler: Any = None
        self.encoders: dict[str, Any] = {}

    def transform(self, lead: LeadProtocol) -> pd.Series:
        """Transform a single lead into a feature vector.

        Args:
            lead: The lead to engineer features for.

        Returns:
            A pandas Series with named features.
        """
        features: dict[str, float] = {}

        # ── Temporal features ────────────────────────────────────────────
        features["days_since_collected"] = self._days_since(
            self._safe_dt(lead, "collected_at")
            or self._safe_dt(lead, "created_at"),
        )
        features["days_since_enriched"] = self._days_since(
            self._safe_dt(lead, "enriched_at"),
        )
        features["days_since_scored"] = self._days_since(
            self._safe_dt(lead, "scored_at"),
        )

        # ── Source quality ───────────────────────────────────────────────
        features["source_tier"] = float(
            SOURCE_TIERS.get(self._safe_str(lead, "source"), 1),
        )
        features["source_age_days"] = self._source_age(
            self._safe_str(lead, "source"),
        )

        # ── Engagement velocity ──────────────────────────────────────────
        features["engagement_velocity"] = self._engagement_velocity(lead)
        features["engagement_acceleration"] = self._engagement_acceleration(lead)

        # ── Company signals ──────────────────────────────────────────────
        features["company_age_years"] = self._company_age(lead)
        features["employee_growth_rate"] = float(
            self._safe_meta(lead, "employee_growth_rate", 0),
        )
        features["hiring_momentum"] = self._hiring_momentum(lead)

        # ── Market signals ───────────────────────────────────────────────
        features["market_momentum"] = self._market_momentum(
            self._safe_str(lead, "industry"),
        )
        features["competitive_intensity"] = self._competitive_intensity(
            self._safe_str(lead, "industry"),
            self._safe_str(lead, "location"),
        )

        # ── Intent recency / frequency ───────────────────────────────────
        features["intent_recency"] = self._intent_recency(lead)
        features["intent_frequency"] = self._intent_frequency(lead)

        return pd.Series(features)

    # ── Temporal Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _days_since(date: datetime | None) -> float:
        """Compute the number of days since *date*."""
        if date is None:
            return 365.0
        return float((datetime.now() - date).days)

    @staticmethod
    def _source_age(source: str) -> float:
        """Return a static estimate of source age in days."""
        age_map: dict[str, float] = {
            "linkedin": 7300.0,  # ~20 years
            "github": 5475.0,  # ~15 years
            "reddit": 5475.0,
            "twitter": 5475.0,
            "naukri": 5475.0,
            "indimart": 3650.0,  # ~10 years
            "tracxn": 1825.0,  # ~5 years
            "yourstory": 1825.0,
            "producthunt": 1825.0,
            "hacker_news": 5475.0,
            "dpiit": 1095.0,  # ~3 years
            "mca21": 3650.0,
            "internshala": 3650.0,
            "gem": 1095.0,
        }
        return age_map.get(source, 365.0)

    # ── Engagement Helpers ───────────────────────────────────────────────

    @staticmethod
    def _engagement_velocity(lead: LeadProtocol) -> float:
        """Compute engagement velocity (events per week)."""
        events = float(getattr(lead, "engagement_metrics", {}).get("total_events", 0))
        collected = getattr(lead, "collected_at", None) or getattr(lead, "created_at", None)
        if collected is None:
            return 0.0
        days = max(float((datetime.now() - collected).days), 1.0)
        weeks = days / 7.0
        return round(events / weeks, 4)

    @staticmethod
    def _engagement_acceleration(lead: LeadProtocol) -> float:
        """Compute engagement acceleration (trend direction).

        Positive values indicate increasing engagement.
        """
        recent = float(
            getattr(lead, "engagement_metrics", {}).get("events_last_7_days", 0),
        )
        previous = float(
            getattr(lead, "engagement_metrics", {}).get("events_previous_7_days", 0),
        )

        if previous == 0:
            return 1.0 if recent > 0 else 0.0
        return float(round((recent - previous) / previous, 4))

    # ── Company Signal Helpers ───────────────────────────────────────────

    @staticmethod
    def _company_age(lead: LeadProtocol) -> float:
        """Estimate company age in years from raw_meta or first seen."""
        founded_year = getattr(lead, "raw_meta", {}).get("founded_year")
        if founded_year:
            try:
                return float(datetime.now().year - int(founded_year))
            except (ValueError, TypeError):
                pass

        collected = getattr(lead, "collected_at", None) or getattr(lead, "created_at", None)
        if collected is None:
            return 0.0
        return round(float((datetime.now() - collected).days) / 365.0, 2)

    @staticmethod
    def _hiring_momentum(lead: LeadProtocol) -> float:
        """Compute hiring momentum score from job count."""
        job_count = int(getattr(lead, "raw_meta", {}).get("job_count", 0))

        if job_count == 0:
            return 0.0
        if job_count <= 3:
            return 0.3
        if job_count <= 10:
            return 0.6
        if job_count <= 25:
            return 0.8
        return 1.0

    # ── Market Signal Helpers ────────────────────────────────────────────

    @staticmethod
    def _market_momentum(industry: str) -> float:
        """Return market momentum multiplier for the given industry."""
        for key, value in INDUSTRY_MOMENTUM.items():
            if key in industry.lower():
                return value
        return 0.5

    @staticmethod
    def _competitive_intensity(industry: str, location: str) -> float:
        """Compute competitive intensity as a signal for outreach timing.

        High competition in a location combined with a competitive industry
        suggests active market = better outreach timing.
        """
        loc_lower = location.lower() if location else ""
        base_intensity = (
            0.7 if any(loc in loc_lower for loc in COMPETITIVE_LOCATIONS) else 0.4
        )

        ind_lower = industry.lower() if industry else ""
        if any(ind in ind_lower for ind in COMPETITIVE_INDUSTRIES):
            base_intensity += 0.2

        return min(base_intensity, 1.0)

    # ── Intent Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _intent_recency(lead: LeadProtocol) -> float:
        """Score how recently intent signals were observed (0-1).

        1.0 = very recent (last 7 days), 0.0 = no signals or very old.
        """
        intent_signals = getattr(lead, "raw_meta", {}).get("intent_signals", [])
        if not intent_signals:
            return 0.0

        recent_count = sum(
            1
            for signal in intent_signals
            if isinstance(signal, dict) and signal.get("recency_days", 999) <= 30
        )
        if recent_count == 0:
            return 0.0
        return min(float(recent_count) / 3.0, 1.0)

    @staticmethod
    def _intent_frequency(lead: LeadProtocol) -> float:
        """Score the frequency of intent signals (0-1)."""
        intent_signals = getattr(lead, "raw_meta", {}).get("intent_signals", [])
        if not intent_signals or not isinstance(intent_signals, list):
            return 0.0
        count = len(intent_signals)
        if count >= 5:
            return 1.0
        if count >= 3:
            return 0.7
        if count >= 1:
            return 0.3
        return 0.0

    # ── Safe Access Helpers ──────────────────────────────────────────────

    @staticmethod
    def _safe_str(lead: object, attr: str) -> str:
        val = getattr(lead, attr, None)
        return str(val) if val is not None else ""

    @staticmethod
    def _safe_dt(lead: object, attr: str) -> datetime | None:
        val = getattr(lead, attr, None)
        return val if isinstance(val, datetime) else None

    @staticmethod
    def _safe_int(lead: object, attr: str) -> int | None:
        val = getattr(lead, attr, None)
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_meta(lead: object, key: str, default: Any = None) -> Any:
        meta = getattr(lead, "raw_meta", None) or {}
        if not isinstance(meta, dict):
            return default
        return meta.get(key, default)
