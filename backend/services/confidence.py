"""
backend/services/confidence.py — Lead Confidence Scoring

CANONICAL confidence formula - NEVER change without updating eval.

The confidence score represents data quality from a combination of:
1. Source trust (how reliable is the data source)
2. Field completeness (how many fields are populated)

CONFIDENCE = field_completeness × source_trust

Usage:
    from backend.services.confidence import compute_confidence, compute_field_score

    confidence = compute_confidence(lead_dict, source="tracxn")
"""
from __future__ import annotations

from typing import Any


# ── Source Trust Levels ─────────────────────────────────────────────────────────

SOURCE_TRUST: dict[str, float] = {
    # Highest trust - verified APIs and official sources
    "github_api": 0.95,      # Verified API, developer confirms email
    "hunter_io": 0.90,       # Email verification service
    "linkedin_api": 0.88,    # Official LinkedIn API

    # High trust - self-posted or editorial with verification
    "hacker_news": 0.82,     # Self-posted by founders
    "yourstory": 0.75,      # Editorial, generally accurate
    "dpiit": 0.78,           # Government registry, verified
    "mca21": 0.85,           # Official corporate registry

    # Medium trust - aggregated or community sources
    "producthunt": 0.72,     # Self-posted but fields often incomplete
    "tracxn": 0.70,          # Aggregated, verify funding independently
    "crunchbase": 0.72,      # Community-edited, mostly accurate

    # Lower trust - user-submitted or may be stale
    "indimart": 0.50,        # User-submitted B2B directory, often stale
    "justdial": 0.45,        # Local business directory
    "generic_web": 0.40,    # Generic web scraping

    # Lowest trust - LLM extraction without source grounding
    "llm_web_scrape": 0.40, # Generic LLM extraction, needs validation
    "llm_vision": 0.35,      # Vision extraction, higher hallucination risk
}


# ── Field Weights ───────────────────────────────────────────────────────────────

FIELD_WEIGHTS: dict[str, float] = {
    # Highest value signals - direct contact information
    "email": 0.28,           # Direct contact, highest value
    "linkedin_url": 0.20,    # Identity anchor, verification source
    "company_domain": 0.15,  # Enrichment unlock, website verification

    # High value signals - qualification information
    "title": 0.12,           # Role/position for targeting
    "tech_stack": 0.10,      # ICP matching for tech companies

    # Medium value signals - context information
    "company_size": 0.08,   # ICP matching for size-based targeting
    "intent_signals": 0.07, # Buying readiness indicators

    # Total = 1.00
}


# ── Core Functions ──────────────────────────────────────────────────────────────

def compute_field_score(lead: dict[str, Any]) -> float:
    """
    Calculate field completeness score.

    Args:
        lead: Extracted lead dictionary

    Returns:
        Float between 0 and 1 representing field completeness
    """
    total_weight = 0.0

    for field, weight in FIELD_WEIGHTS.items():
        value = lead.get(field)

        # Check if field is populated
        if value is None:
            continue

        # For strings, check if not empty
        if isinstance(value, str) and value.strip():
            total_weight += weight

        # For lists, check if not empty
        elif isinstance(value, list) and len(value) > 0:
            total_weight += weight

        # For numbers, check if not zero
        elif isinstance(value, (int, float)) and value != 0:
            total_weight += weight

    return min(total_weight, 1.0)  # Cap at 1.0


def compute_confidence(lead: dict[str, Any], source: str) -> float:
    """
    Compute overall confidence score for extracted lead.

    Args:
        lead: Extracted lead dictionary
        source: Data source identifier

    Returns:
        Float between 0 and 1 representing overall confidence
    """
    # Get source trust level (default to lowest)
    source_trust = SOURCE_TRUST.get(source, 0.40)

    # Calculate field completeness
    field_score = compute_field_score(lead)

    # Final confidence = field_completeness × source_trust
    confidence = field_score * source_trust

    return round(confidence, 3)


def get_source_trust(source: str) -> float:
    """
    Get trust level for a data source.

    Args:
        source: Data source identifier

    Returns:
        Float between 0 and 1 representing source trust level
    """
    return SOURCE_TRUST.get(source, 0.40)


def explain_confidence(lead: dict[str, Any], source: str) -> dict[str, Any]:
    """
    Explain the confidence calculation for debugging.

    Returns a detailed breakdown of the confidence calculation.
    """
    source_trust = SOURCE_TRUST.get(source, 0.40)
    field_score = compute_field_score(lead)

    # Calculate per-field contribution
    field_contributions = {}
    for field, weight in FIELD_WEIGHTS.items():
        value = lead.get(field)
        is_populated = bool(
            value is not None and
            (isinstance(value, str) and value.strip() or
             isinstance(value, list) and len(value) > 0 or
             isinstance(value, (int, float)) and value != 0)
        )
        field_contributions[field] = {
            "weight": weight,
            "populated": is_populated,
            "contribution": weight if is_populated else 0,
        }

    return {
        "source": source,
        "source_trust": source_trust,
        "field_completeness": field_score,
        "final_confidence": round(field_score * source_trust, 3),
        "field_breakdown": field_contributions,
    }