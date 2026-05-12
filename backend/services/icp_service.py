"""
backend/services/icp_service.py — Ideal Customer Profile Engine

Provides:
    1. Natural language ICP parsing (Gemini Flash)
    2. Semantic lead matching (pgvector)
    3. Deterministic scoring layer
    4. Temporal decay for ICP signals

Usage:
    from backend.services.icp_service import parse_icp, match_lead_to_icp

    icp = await parse_icp("CTOs at Series A SaaS startups using React")
    leads = await find_matching_leads(icp, session)
"""
from __future__ import annotations

import functools
import json
import math
import structlog
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.icp import ICP
from backend.shared.models import Lead
from backend.shared.stream import redis_stream

logger = structlog.get_logger()


def cache_result(expire_seconds: int, key_template: str):
    """Redis cache decorator for async functions."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if not redis_stream._r:
                return await fn(*args, **kwargs)
            cache_key = key_template.format(*args, **kwargs)
            cached = await redis_stream._r.get(cache_key)
            if cached:
                return json.loads(cached)
            result = await fn(*args, **kwargs)
            await redis_stream._r.setex(cache_key, expire_seconds, json.dumps(result))
            return result
        return wrapper
    return decorator


# ── ICP Parsing ──────────────────────────────────────────────────────────────────

async def parse_icp(description: str) -> dict[str, Any]:
    """
    Parse natural language ICP description into structured format.

    Uses Gemini Flash for natural language understanding.
    Lazy-imports from gemini_service to avoid GCP auth at import time.

    Example:
        Input: "CTOs at Indian SaaS startups 20-200 employees using React"
        Output: {
            "target_titles": ["CTO", "VP Engineering"],
            "target_industries": ["SaaS"],
            "target_sizes": ["11-50", "51-200"],
            "target_locations": ["India"],
            "target_stack": ["React"],
            "funding_stages": ["series-a"],
        }
    """
    from backend.llm.gemini_service import parse_natural_language_icp
    return await parse_natural_language_icp(description)


# ── Temporal Decay ───────────────────────────────────────────────────────────────

def icp_decay_score(
    icp_created_at: datetime,
    half_life_days: int = 30,
) -> float:
    """
    Calculate decayed ICP score based on age.

    ICPs become less relevant over time as market conditions change.
    Uses exponential decay with configurable half-life.

    Args:
        icp_created_at: When the ICP was created
        half_life_days: Days until ICP loses half its relevance (default 30)

    Returns:
        Float between 0 and 1 representing ICP freshness

    Example:
        icp_created = datetime(2024, 1, 1)
        score = icp_decay_score(icp_created)  # Returns ~0.5 after 30 days
    """
    age_days = (datetime.utcnow() - icp_created_at).days
    if age_days < 0:
        return 1.0  # Future ICP (clock skew) - treat as fresh

    decay_factor = math.exp(-0.693 * age_days / half_life_days)
    return round(decay_factor, 3)


# ── Deterministic Scoring ────────────────────────────────────────────────────────

def calculate_icp_score(lead: Lead | dict[str, Any], icp: ICP | dict[str, Any]) -> float:
    """
    Calculate deterministic ICP fit score (0-100).

    Scoring weights:
        - Industry match: 25 points (binary)
        - Company size match: 20 points (linear decay from center)
        - Tech stack overlap: 20 points (Jaccard index)
        - Funding stage match: 15 points (binary)
        - Location match: 10 points (binary)
        - Intent signals: 10 points (bonus for each matching signal)

    Args:
        lead: Lead model or dictionary
        icp: ICP model or dictionary

    Returns:
        Float between 0 and 100 representing ICP fit
    """
    # Convert to dict if needed
    lead_dict = lead if isinstance(lead, dict) else {
        "industry": getattr(lead, "industry", None),
        "company_size": getattr(lead, "company_size", None),
        "tech_stack": getattr(lead, "tech_stack", []),
        "funding_stage": getattr(lead, "funding_stage", None),
        "location": getattr(lead, "location", None),
        "intent_signals": getattr(lead, "intent_signals", []),
    }

    icp_dict = icp if isinstance(icp, dict) else {
        "target_industries": getattr(icp, "target_industries", []),
        "target_sizes": getattr(icp, "target_sizes", []),
        "target_stack": getattr(icp, "target_stack", []),
        "funding_stages": getattr(icp, "funding_stages", []),
        "target_locations": getattr(icp, "target_locations", []),
        "required_signals": getattr(icp, "required_signals", []),
    }

    score = 0.0

    # Industry match (25 points)
    if lead_dict.get("industry") in icp_dict.get("target_industries", []):
        score += 25

    # Company size match (20 points, linear decay)
    lead_size = lead_dict.get("company_size", "")
    target_sizes = icp_dict.get("target_sizes", [])
    if lead_size in target_sizes:
        score += 20
    elif target_sizes:
        # Partial score for adjacent sizes
        size_order = ["1-10", "11-50", "51-200", "201-500", "500+"]
        try:
            lead_idx = size_order.index(lead_size)
            min_idx = min(size_order.index(s) for s in target_sizes if s in size_order)
            max_idx = max(size_order.index(s) for s in target_sizes if s in size_order)
            if min_idx <= lead_idx <= max_idx:
                score += 10  # Half score for adjacent size
        except (ValueError, IndexError):
            pass

    # Tech stack overlap (20 points, Jaccard index)
    lead_stack = set(lead_dict.get("tech_stack", []) or [])
    icp_stack = set(icp_dict.get("target_stack", []) or [])
    if lead_stack and icp_stack:
        overlap = len(lead_stack & icp_stack) / max(len(lead_stack | icp_stack), 1)
        score += overlap * 20

    # Funding stage match (15 points)
    if lead_dict.get("funding_stage") in icp_dict.get("funding_stages", []):
        score += 15

    # Location match (10 points)
    if lead_dict.get("location") in icp_dict.get("target_locations", []):
        score += 10

    # Intent signals bonus (up to 10 points)
    lead_signals = set(lead_dict.get("intent_signals", []) or [])
    required_signals = set(icp_dict.get("required_signals", []) or [])
    if required_signals:
        matched_signals = len(lead_signals & required_signals)
        score += min(matched_signals * 5, 10)  # Max 10 points

    return min(score, 100.0)


# ── Semantic Matching ────────────────────────────────────────────────────────────

async def find_matching_leads(
    icp: ICP,
    session: AsyncSession,
    limit: int = 100,
    min_confidence: float = 0.50,
) -> list[tuple[Lead, float]]:
    """
    Find leads matching an ICP using pgvector semantic search.

    Returns leads ranked by ICP fit score (deterministic + semantic).

    Args:
        icp: ICP model instance
        session: Database session
        limit: Maximum leads to return
        min_confidence: Minimum confidence threshold

    Returns:
        List of (Lead, icp_score) tuples, sorted by score descending
    """
    from backend.llm.gemini_service import get_embedding

    # Generate ICP embedding from description
    icp_text = f"""
    {' '.join(icp.target_titles or [])}
    {' '.join(icp.target_industries or [])}
    {' '.join(icp.target_stack or [])}
    """
    icp_embedding = await get_embedding(icp_text)

    if not icp_embedding:
        # Fallback to deterministic-only matching
        result = await session.execute(
            select(Lead)
            .where(Lead.confidence >= min_confidence)
            .limit(limit * 2)
        )
        leads = result.scalars().all()
        return [(lead, calculate_icp_score(lead, icp)) for lead in leads]

    # pgvector semantic search
    try:

        result = await session.execute(
            select(Lead, Lead.embedding.cosine_distance(icp_embedding).label("semantic_dist"))
            .where(Lead.confidence >= min_confidence)
            .where(Lead.embedding.isnot(None))
            .order_by("semantic_dist")
            .limit(limit * 2)
        )
    except ImportError:
        logger.warning("pgvector_not_installed_using_fallback")
        result = await session.execute(
            select(Lead)
            .where(Lead.confidence >= min_confidence)
            .limit(limit * 2)
        )

    # Apply temporal decay to ICP
    icp_decay = icp_decay_score(icp.created_at)

    leads_with_scores = []
    for row in result:
        lead = row[0] if isinstance(row, tuple) else row
        semantic_dist = row[1] if isinstance(row, tuple) and len(row) > 1 else 1.0

        # Combine deterministic score with semantic similarity
        deterministic_score = calculate_icp_score(lead, icp)
        semantic_score = max(0, 1 - semantic_dist) * 30  # Up to 30 points for semantic match

        # Apply temporal decay to ICP score
        total_score = min((deterministic_score + semantic_score) * icp_decay, 100.0)
        leads_with_scores.append((lead, total_score))

    # Sort by total score descending
    leads_with_scores.sort(key=lambda x: x[1], reverse=True)
    return leads_with_scores[:limit]