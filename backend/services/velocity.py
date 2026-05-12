"""
services/velocity.py — Real-time cross-source signal velocity tracker.

Uses Redis Sorted Sets (ZSET):
  - Key:    velocity:company:<name_lower>
  - Member: "<source>:<timestamp>"
  - Score:  Unix timestamp (float)

ZADD adds a new member; ZCOUNT over [now-window, now] gives signal count.
Old entries are pruned with ZREMRANGEBYSCORE to avoid unbounded growth.

Usage:
    tracker = VelocityTracker()
    await tracker.connect()
    await tracker.record_signal("Acme Corp", "reddit")
    count = await tracker.get_signal_count("Acme Corp")   # -> int
    await tracker.disconnect()
"""
from __future__ import annotations

import time

import redis.asyncio as aioredis

from backend.shared.config import settings

_KEY_PREFIX    = "velocity:company:"
_WINDOW_SECS   = 7 * 24 * 3600   # 7-day rolling window
_MAX_BONUS_SOURCES = 5            # cap velocity burst bonus


class VelocityTracker:
    """Async Redis ZSET velocity tracker — one instance per application."""

    def __init__(self, redis_url: str = "") -> None:
        self._url: str = redis_url or settings.REDIS_URL
        self._client: aioredis.Redis | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._client = aioredis.from_url(self._url, decode_responses=True)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Write ──────────────────────────────────────────────────────────────────

    async def record_signal(self, company_name: str, source: str) -> None:
        """Record one signal for company_name from source. No-op if Redis down."""
        if not self._client or not company_name:
            return
        key    = _KEY_PREFIX + company_name.lower().strip()
        now    = time.time()
        member = f"{source}:{now}"
        cutoff = now - _WINDOW_SECS
        try:
            pipe = self._client.pipeline()
            pipe.zadd(key, {member: now})
            pipe.zremrangebyscore(key, "-inf", cutoff)
            pipe.expire(key, _WINDOW_SECS)
            await pipe.execute()
        except Exception:
            pass   # velocity is best-effort; never raise

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get_signal_count(self, company_name: str) -> int:
        """Number of signals for company_name in the rolling window."""
        if not self._client or not company_name:
            return 0
        key    = _KEY_PREFIX + company_name.lower().strip()
        cutoff = time.time() - _WINDOW_SECS
        try:
            count = await self._client.zcount(key, cutoff, "+inf")
            return int(count)
        except Exception:
            return 0

    async def get_top_companies(self, limit: int = 20) -> list[dict]:
        """Return top companies by signal count in the rolling window."""
        if not self._client:
            return []
        try:
            pattern = _KEY_PREFIX + "*"
            keys    = [k async for k in self._client.scan_iter(match=pattern)]
            cutoff  = time.time() - _WINDOW_SECS
            results = []
            for key in keys:
                count = await self._client.zcount(key, cutoff, "+inf")
                if count:
                    company = key.removeprefix(_KEY_PREFIX)
                    results.append({"company": company, "signal_count": int(count)})
            results.sort(key=lambda x: x["signal_count"], reverse=True)
            return results[:limit]
        except Exception:
            return []

    async def get_velocity_map(self, company_names: list[str]) -> dict[str, int]:
        """Batch-fetch counts for a list of company names. Efficient pipeline."""
        if not self._client or not company_names:
            return {}
        cutoff = time.time() - _WINDOW_SECS
        keys   = [_KEY_PREFIX + n.lower().strip() for n in company_names if n]
        try:
            pipe = self._client.pipeline()
            for key in keys:
                pipe.zcount(key, cutoff, "+inf")
            counts = await pipe.execute()
            return {
                name: int(count)
                for name, count in zip(company_names, counts, strict=True)
                if isinstance(count, int)
            }
        except Exception:
            return {}


# ── Singleton ─────────────────────────────────────────────────────────────────
velocity_tracker = VelocityTracker()
