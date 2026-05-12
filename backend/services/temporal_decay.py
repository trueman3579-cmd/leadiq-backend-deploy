"""
temporal_decay.py — Intent-Specific Temporal Decay Scoring (Day 15)

Applies exponential decay to lead scores based on post age and intent type.
Intent-specific half-lives reflect urgency differences in B2B lead data.

Formula:  score_factor = 0.5 ^ (hours_elapsed / half_life_hours)
For old posts: min_score = 0.05 (never fully zeros out)
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

# Half-lives in hours — reflect urgency per intent type
INTENT_HALF_LIVES: dict[str, float] = {
    "hiring": 72.0,        # 3 days — urgent, jobs fill fast
    "job_search": 168.0,    # 7 days — moderately urgent
    "b2b_sales": 336.0,     # 14 days — standard B2B cycle
    "opportunity": 504.0,   # 21 days — less time-sensitive
    "other": 240.0,         # 10 days — default
}
DEFAULT_HALF_LIFE = 240.0   # 10 days
MIN_SCORE_FACTOR = 0.05      # never decay below 5%


def get_half_life(intent: str) -> float:
    """Returns half-life in hours for the given intent."""
    if not intent:
        return DEFAULT_HALF_LIFE
    normalized = intent.lower().strip()
    return INTENT_HALF_LIVES.get(normalized, DEFAULT_HALF_LIFE)


def compute_decay_factor(
    published_at: datetime | str | None,
    intent: str = "",
    now: datetime | None = None,
) -> float:
    """
    Returns a multiplier (0.05–1.0) for lead score based on age.
    - 0 hours old → 1.0
    - half_life hours old → 0.5
    - very old → 0.05 (floor)
    """
    if published_at is None:
        return 0.5  # conservative default for missing timestamps

    if isinstance(published_at, str):
        try:
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return 0.5

    now = now or datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)

    age_hours = (now - published_at).total_seconds() / 3600.0
    if age_hours <= 0:
        return 1.0

    half_life = get_half_life(intent)
    factor = 0.5 ** (age_hours / half_life)
    return max(MIN_SCORE_FACTOR, factor)


def apply_decay(
    base_score: float,
    published_at: datetime | str | None,
    intent: str = "",
) -> float:
    """Applies temporal decay to a base score. Returns decayed score (0-10 scale)."""
    factor = compute_decay_factor(published_at, intent)
    return round(base_score * factor, 3)


def get_decay_metadata(
    published_at: datetime | str | None,
    intent: str = "",
) -> dict:
    """Returns detailed decay metadata for audit trail."""
    factor = compute_decay_factor(published_at, intent)
    half_life = get_half_life(intent)
    return {
        "decay_factor": round(factor, 4),
        "half_life_hours": half_life,
        "intent": intent or "unknown",
        "decayed": factor < 1.0,
    }
