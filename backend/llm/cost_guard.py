"""
backend/llm/cost_guard.py — Gemini Token Budget Enforcement (Day 10: Cost Stable)

Two-gate budget check: daily (2M tokens) + hourly (83K tokens).
Queue-on-limit: tasks go to Redis Stream when budget exhausted, NOT heuristic fallback.

Usage:
    from backend.llm.cost_guard import check_budget, consume_budget, queue_for_later

    if not await check_budget(tokens_requested):
        await queue_for_later("analyze_lead", {"url": url, "source": source})
        return None
    # ... call Gemini ...
    await consume_budget(tokens_used)
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, UTC

import redis.asyncio as aioredis

from backend.shared.config import settings

logger = logging.getLogger(__name__)

DAILY_TOKEN_BUDGET = settings.GEMINI_DAILY_BUDGET
HOURLY_BUDGET = settings.GEMINI_HOURLY_BUDGET
QUEUE_STREAM = settings.GEMINI_QUEUE_STREAM
QUEUE_MAX_SIZE = settings.GEMINI_QUEUE_MAX_SIZE

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


def _daily_key() -> str:
    return f"gemini_tokens_{date.today().isoformat()}"


def _hourly_key() -> str:
    now = datetime.now(UTC)
    return f"gemini_tokens_hourly_{now.strftime('%Y-%m-%d_%H')}"


async def check_budget(tokens_requested: int) -> bool:
    """Two-gate budget check. Returns True if both daily + hourly limits allow the call."""
    r = await get_redis()
    try:
        daily_used = int(await r.get(_daily_key()) or 0)
        if daily_used + tokens_requested > DAILY_TOKEN_BUDGET:
            logger.warning(
                "gemini_daily_budget_exhausted used=%d requested=%d limit=%d",
                daily_used, tokens_requested, DAILY_TOKEN_BUDGET,
            )
            return False

        hourly_used = int(await r.get(_hourly_key()) or 0)
        if hourly_used + tokens_requested > HOURLY_BUDGET:
            logger.warning(
                "gemini_hourly_budget_exhausted used=%d requested=%d limit=%d hour=%d",
                hourly_used, tokens_requested, HOURLY_BUDGET,
                datetime.now(UTC).hour,
            )
            return False

        return True
    except Exception as exc:
        logger.error("gemini_budget_check_failed error=%s", exc)
        return True  # fail-open


async def consume_budget(tokens_used: int) -> None:
    """Atomically increment BOTH daily and hourly counters after a Gemini call."""
    r = await get_redis()
    try:
        pipe = r.pipeline()
        daily_k = _daily_key()
        hourly_k = _hourly_key()

        pipe.incrby(daily_k, tokens_used)
        pipe.expire(daily_k, 86400)
        pipe.incrby(hourly_k, tokens_used)
        pipe.expire(hourly_k, 3600)
        await pipe.execute()

        logger.info(
            "gemini_budget_consumed tokens=%d daily_key=%s hourly_key=%s",
            tokens_used, daily_k, hourly_k,
        )
    except Exception as exc:
        logger.error("gemini_consume_budget_failed error=%s", exc)


async def queue_for_later(task_name: str, task_args: dict) -> bool:
    """Push a task to the delay queue when budget is exhausted. Returns False if queue full."""
    r = await get_redis()
    try:
        queue_len = await r.xlen(QUEUE_STREAM)
        if queue_len >= QUEUE_MAX_SIZE:
            logger.error(
                "gemini_queue_full queue=%s size=%d limit=%d",
                QUEUE_STREAM, queue_len, QUEUE_MAX_SIZE,
            )
            return False

        await r.xadd(
            QUEUE_STREAM,
            {"task_name": task_name, "task_args": json.dumps(task_args)},
            maxlen=QUEUE_MAX_SIZE,
        )
        logger.info(
            "gemini_task_queued task=%s queue_depth=%d",
            task_name, queue_len + 1,
        )
        return True
    except Exception as exc:
        logger.error("gemini_queue_failed error=%s", exc)
        return False


async def get_budget_status() -> dict:
    """Returns current budget status for monitoring."""
    r = await get_redis()
    now = datetime.now(UTC)
    try:
        daily_used = int(await r.get(_daily_key()) or 0)
        hourly_used = int(await r.get(_hourly_key()) or 0)
        queue_depth = await r.xlen(QUEUE_STREAM)

        return {
            "daily": {
                "used": daily_used,
                "limit": DAILY_TOKEN_BUDGET,
                "remaining": max(0, DAILY_TOKEN_BUDGET - daily_used),
                "pct_used": round(daily_used / DAILY_TOKEN_BUDGET * 100, 1),
            },
            "hourly": {
                "used": hourly_used,
                "limit": HOURLY_BUDGET,
                "remaining": max(0, HOURLY_BUDGET - hourly_used),
                "hour_utc": now.hour,
                "resets_in_minutes": 60 - now.minute,
            },
            "queue": {
                "depth": queue_depth,
                "max_size": QUEUE_MAX_SIZE,
                "stream": QUEUE_STREAM,
            },
            "estimated_daily_cost_usd": round(daily_used / 1_000_000 * 0.075, 4),
            "trial_budget_remaining_usd": round(
                300.0 - (daily_used / 1_000_000 * 0.075), 2
            ),
        }
    except Exception as exc:
        logger.error("gemini_budget_status_failed error=%s", exc)
        return {"error": str(exc)}


async def reset_budget() -> None:
    """Reset today's budget counter (admin/testing only)."""
    r = await get_redis()
    await r.delete(_daily_key(), _hourly_key())
    logger.info("gemini_budget_reset date=%s", date.today().isoformat())
