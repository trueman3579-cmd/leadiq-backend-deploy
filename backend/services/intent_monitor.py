"""
backend/services/intent_monitor.py — Intent Signal Monitoring

Monitors and refreshes intent signals for leads:
    - Temporal decay (signals become less valuable over time)
    - Quota-guarded API calls (stay within free tier limits)
    - Redis Pub/Sub events for realtime dashboard

Celery Beat Schedule: Every 30 minutes

Usage:
    from backend.services.intent_monitor import refresh_intent_signals

    await refresh_intent_signals()
"""
from __future__ import annotations

import json
import math
import structlog
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis

from backend.shared.config import settings
from backend.shared.stream import redis_stream

logger = structlog.get_logger()


# ── Temporal Decay ───────────────────────────────────────────────────────────────

def decayed_signal_score(
    signal_date: datetime,
    half_life_days: int = 45,
) -> float:
    """
    Calculate decayed signal score based on age.

    Karpathy's insight: stale signals = misleading scores.
    Uses exponential decay with configurable half-life.

    Args:
        signal_date: When the signal was detected
        half_life_days: Days until signal loses half its value (default 45)

    Returns:
        Float between 0 and 1 representing signal freshness

    Example:
        signal_detected = datetime(2024, 1, 1)
        score = decayed_signal_score(signal_detected)  # Returns ~0.5 after 45 days
    """
    age_days = (datetime.utcnow() - signal_date).days
    if age_days < 0:
        return 1.0  # Future signal (clock skew) - treat as fresh

    decay_factor = math.exp(-0.693 * age_days / half_life_days)
    return round(decay_factor, 3)


# ── Quota Management ─────────────────────────────────────────────────────────────

# Free tier API quotas (per day)
DAILY_QUOTAS = {
    "newsapi": 100,      # 100 requests/day free tier
    "github": 4500,      # Stay under 5000/hour limit
    "hunter": 25,        # Email finder
}


async def check_quota(api_name: str) -> bool:
    """
    Check if quota is available for the specified API.

    Args:
        api_name: API identifier (newsapi, github, hunter)

    Returns:
        True if quota available, False if exhausted
    """
    r = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"quota:{api_name}:{today}"
        used = int(await r.get(key) or 0)

        if used >= DAILY_QUOTAS.get(api_name, 100):
            logger.warning("api_quota_exhausted", api=api_name, used=used)
            return False

        # Increment quota
        await r.incr(key)
        await r.expire(key, 86400)  # 24-hour TTL
        return True

    except Exception as exc:
        logger.error("quota_check_error", api=api_name, error=str(exc))
        return True  # Fail-open


# ── Intent Signal Detection ───────────────────────────────────────────────────────

async def detect_signals(company_domain: str) -> list[dict[str, Any]]:
    """
    Detect intent signals for a company.

    Signal types:
        - hiring: Company is hiring (job boards, careers page)
        - funding: Recent funding round
        - news: Company in recent news
        - social: Social media activity spike
        - technology: Tech stack changes detected

    Args:
        company_domain: Company website domain

    Returns:
        List of detected signals with decay scores
    """
    signals = []

    # Check NewsAPI for recent news
    if await check_quota("newsapi"):
        # TODO: Implement NewsAPI call
        # news = await fetch_news(company_domain)
        # if news:
        #     signals.append({
        #         "type": "news",
        #         "detected_at": datetime.utcnow(),
        #         "source": "newsapi",
        #         "data": news,
        #     })
        pass

    # Check GitHub for hiring signals
    if await check_quota("github"):
        # TODO: Implement GitHub API call
        # repos = await fetch_github_hiring(company_domain)
        # if repos:
        #     signals.append({
        #         "type": "hiring",
        #         "detected_at": datetime.utcnow(),
        #         "source": "github",
        #         "data": repos,
        #     })
        pass

    return signals


# ── Main Refresh Task ────────────────────────────────────────────────────────────

async def refresh_intent_signals(limit: int = 10) -> None:
    """
    Refresh intent signals for stale leads.

    Celery Beat: Every 30 minutes

    Args:
        limit: Maximum companies to process per run
    """
    from backend.shared.db import get_db_session
    from backend.shared.repository import LeadRepo

    async with get_db_session() as session:
        lead_repo = LeadRepo(session)

        # Get stale leads
        stale_leads = await lead_repo.get_stale_signals(limit=limit)
        logger.info("intent_refresh_start", stale_count=len(stale_leads))

        processed = 0
        for lead in stale_leads:
            signals = await detect_signals(lead.company_domain or "")

            if signals:
                # Apply temporal decay to existing signals
                updated_signals = _merge_signals(
                    existing=lead.intent_signals or [],
                    new=signals,
                )

                # Update the lead
                await lead_repo.update_fields(
                    lead_id=str(lead.id),
                    updates={
                        "intent_signals": updated_signals,
                        "last_signal_update": datetime.utcnow(),
                    },
                )

                # Emit Redis Pub/Sub event for realtime dashboard
                await redis_stream.publish(
                    channel="signals:new",
                    message=json.dumps({
                        "lead_id": str(lead.id),
                        "company": lead.company_name,
                        "signals": signals,
                        "detected_at": datetime.utcnow().isoformat(),
                    }),
                )

                # Emit domain event
                from backend.events.emitter import emit
                await emit("signal_detected", {
                    "lead_id": str(lead.id),
                    "company": lead.company_name,
                    "signals": signals,
                    "detected_at": datetime.utcnow().isoformat(),
                })

                processed += 1
                logger.info(
                    "intent_refresh_signal_detected",
                    lead_id=str(lead.id),
                    company=lead.company_name,
                    signal_count=len(signals),
                )

        logger.info("intent_refresh_complete", processed=processed, stale_leads=len(stale_leads))


def _merge_signals(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge new signals with existing, applying temporal decay.

    Strategy:
        1. Keep existing signals that are still fresh
        2. Add new signals
        3. Apply decay to all signals

    Args:
        existing: Existing intent signals
        new: Newly detected signals

    Returns:
        Merged list of signals with decay applied
    """
    from backend.services.intent_monitor import decayed_signal_score

    # Combine existing and new
    all_signals = existing.copy()

    # Add new signals with decay applied at detection time
    for new_signal in new:
        decayed_score = decayed_signal_score(new_signal.get("detected_at", datetime.utcnow()))
        new_signal["decay_score"] = decayed_score
        all_signals.append(new_signal)

    # Filter out very old signals (decay < 0.2)
    filtered = [
        s for s in all_signals
        if s.get("decay_score", 1.0) >= 0.2
    ]

    # Sort by decay score (highest first)
    filtered.sort(key=lambda s: s.get("decay_score", 0.0), reverse=True)

    return filtered


async def get_stale_signal_companies(limit: int) -> list[Any]:
    """
    Get companies with stale intent signals.

    Companies are stale if:
        - No signal update in 24 hours
        - Last signal decayed below 0.5

    Returns:
        List of company objects needing refresh
    """
    # Deprecated: Use LeadRepo.get_stale_signals instead
    from backend.shared.db import get_db_session
    from backend.shared.repository import LeadRepo

    async with get_db_session() as session:
        lead_repo = LeadRepo(session)
        leads = await lead_repo.get_stale_signals(limit=limit)
        return leads


async def update_intent_signals(
    company_id: str,
    signals: list[dict[str, Any]],
) -> None:
    """
    Update intent signals for a company.

    Applies temporal decay to existing signals and merges new ones.

    Deprecated: Use refresh_intent_signals() which handles the full workflow.
    """
    # Deprecated: This is now handled by refresh_intent_signals()
    logger.warning(
        "deprecated_intent_update",
        company_id=company_id,
        signal_count=len(signals),
    )
