"""
feedback_loop.py — LeadEvent Feedback Flywheel (Day 17)

Closed-loop learning: every user action (view, click, save, dismiss, feedback)
feeds back into scoring weights. The system gets smarter with every interaction.

Flow:
  User Action → LeadEvent logged → Aggregate patterns → Update ICP weights
                                                                ↓
                                          Profile.feedback_adjustments updated
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# How much each event type influences scoring adjustments
EVENT_WEIGHTS: dict[str, float] = {
    "approved": 0.15,
    "rejected": -0.15,
    "converted": 0.25,
    "email_replied": 0.20,
    "email_bounced": -0.20,
    "field_edited": -0.05,
    "enriched": 0.02,
    "signal_fired": 0.10,
}

# Per-rating deltas for feedback events
RATING_DELTA: dict[int, float] = {5: 0.12, 4: 0.06, 3: 0.0, 2: -0.06, 1: -0.12}


def compute_event_bonus(event_type: str) -> float:
    """Returns score adjustment for a single LeadEvent."""
    return EVENT_WEIGHTS.get(event_type, 0.0)


def aggregate_event_impact(events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregates impact of a batch of LeadEvents for flywheel learning.

    Returns {total_adjustment, by_type, net_direction, confidence}
    """
    if not events:
        return {
            "total_adjustment": 0.0,
            "by_type": {},
            "net_direction": "neutral",
            "confidence": 0.0,
        }

    by_type: dict[str, float] = {}
    total = 0.0
    for e in events:
        event_type = e.get("event_type", "")
        weight = EVENT_WEIGHTS.get(event_type, 0.0)
        by_type[event_type] = by_type.get(event_type, 0.0) + weight
        total += weight

    # Confidence grows with volume
    confidence = min(1.0, len(events) / 50.0)

    if total > 0.05:
        direction = "positive"
    elif total < -0.05:
        direction = "negative"
    else:
        direction = "neutral"

    return {
        "total_adjustment": round(total, 4),
        "by_type": {k: round(v, 4) for k, v in by_type.items()},
        "net_direction": direction,
        "confidence": round(confidence, 3),
        "event_count": len(events),
    }


def update_icp_weights_from_feedback(
    current_weights: dict[str, float],
    feedback_impact: dict[str, Any],
    learning_rate: float = 0.05,
) -> dict[str, float]:
    """
    Updates ICP scoring weights based on aggregated feedback.

    Positive feedback → stronger industry_match, intent_signal
    Negative feedback → reduce industry_match, increase intercept penalty
    """
    updated = dict(current_weights)
    adjustment = feedback_impact.get("total_adjustment", 0.0)

    # Industry and intent signals get stronger on positive feedback
    updated["industry_match"] = round(
        updated.get("industry_match", 2.5) + adjustment * learning_rate * 2.0, 2
    )
    updated["intent_signal_strength"] = round(
        updated.get("intent_signal_strength", 3.0) + adjustment * learning_rate * 1.5, 2
    )

    # Intercept moves opposite direction (harder threshold on negative)
    updated["intercept"] = round(
        updated.get("intercept", -2.0) - adjustment * learning_rate * 0.5, 2
    )

    # Clamp weights to reasonable ranges
    for key in updated:
        if key == "intercept":
            updated[key] = max(-5.0, min(2.0, updated[key]))
        else:
            updated[key] = max(0.5, min(6.0, updated[key]))

    logger.info(
        "icp_weights_updated",
        adjustment=adjustment,
        new_industry=updated["industry_match"],
        new_intent=updated["intent_signal_strength"],
    )
    return updated


def compute_email_validity_rate(
    feedbacks: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Computes email validity rate from feedback data.

    Returns {rate, total_emails, valid_emails, confidence}
    """
    if not feedbacks:
        return {"rate": None, "total_emails": 0, "valid_emails": 0, "confidence": 0.0}

    total = len(feedbacks)
    valid = sum(1 for f in feedbacks if f.get("label") in ("good", "valid"))
    rate = round(valid / total, 3) if total > 0 else None

    return {
        "rate": rate,
        "total_emails": total,
        "valid_emails": valid,
        "confidence": min(1.0, total / 30.0),
    }


def should_trigger_quality_freeze(email_validity_rate: float | None) -> bool:
    """Returns True if email validity rate drops below 60% threshold."""
    return email_validity_rate is not None and email_validity_rate < 0.60
