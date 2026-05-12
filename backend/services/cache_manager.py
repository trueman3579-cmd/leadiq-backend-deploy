"""
backend/services/cache_manager.py -- Multi-Tier Caching Layer for LeadIQ

Provides a Redis-backed distributed cache with cache-aside pattern, pattern-based
invalidation, and hit-rate tracking. Designed to achieve >70% cache hit rate for
frequently accessed lead and company data.

Usage:
    from backend.services.cache_manager import CacheManager

    cache = CacheManager("redis://localhost:6379/0")

    # Cache-aside pattern
    data = await cache.get_or_compute("company:acme", lambda: fetch_from_db("acme"), ttl=3600)

    # Manual operations
    await cache.set("key", value, ttl=300)
    value = await cache.get("key")
    await cache.invalidate_pattern("company:*")

    # Stats
    stats = await cache.get_stats()
"""
from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class CacheManager:
    """Redis-backed distributed cache with hit-rate tracking.

    Implements the cache-aside pattern: on read, check cache first; on miss,
    compute the value via a factory function, store in cache, and return.
    Hit rates are tracked in Redis for observability.
    """

    def __init__(self, redis_url: str, default_ttl: int = 3600) -> None:
        """Initialise the cache manager.

        Args:
            redis_url: Redis connection URL (e.g. redis://localhost:6379/0).
            default_ttl: Default TTL in seconds for cached entries (1 hour).
        """
        self.client: aioredis.Redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
        )
        self.default_ttl: int = default_ttl

    # ── Core Operations ───────────────────────────────────────────────────────────

    async def get(self, key: str) -> Any | None:
        """Retrieve a value from the cache.

        Args:
            key: Cache key.

        Returns:
            The deserialised value if found, None otherwise.
        """
        try:
            raw = await self.client.get(key)
            if raw is not None:
                await self._record_hit(key)
                return json.loads(raw)
            await self._record_miss(key)
            return None
        except Exception as exc:
            logger.warning("cache_get_failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store a value in the cache with a TTL.

        Args:
            key: Cache key.
            value: Value to cache (must be JSON-serialisable).
            ttl: Time-to-live in seconds. Uses default_ttl if None.

        Returns:
            True if the operation succeeded, False otherwise.
        """
        resolved_ttl = ttl if ttl is not None else self.default_ttl
        try:
            serialised = json.dumps(value, default=str)
            await self.client.setex(key, resolved_ttl, serialised)
            logger.debug("cache_set", key=key, ttl=resolved_ttl)
            return True
        except Exception as exc:
            logger.warning("cache_set_failed", key=key, error=str(exc))
            return False

    async def delete(self, key: str) -> bool:
        """Delete a single key from the cache.

        Args:
            key: Cache key to delete.

        Returns:
            True if the key was deleted, False if it did not exist or on error.
        """
        try:
            result = await self.client.delete(key)
            if result:
                logger.debug("cache_deleted", key=key)
            return bool(result)
        except Exception as exc:
            logger.warning("cache_delete_failed", key=key, error=str(exc))
            return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            key: Cache key.

        Returns:
            True if the key exists, False otherwise.
        """
        try:
            return bool(await self.client.exists(key))
        except Exception as exc:
            logger.warning("cache_exists_failed", key=key, error=str(exc))
            return False

    # ── Cache-Aside Pattern ────────────────────────────────────────────────────────

    async def get_or_compute(
        self,
        key: str,
        factory: Callable[[], Coroutine[Any, Any, Any]],
        ttl: int | None = None,
    ) -> Any:
        """Cache-aside pattern: return cached value or compute and cache.

        Args:
            key: Cache key.
            factory: Async callable that produces the value on a cache miss.
            ttl: Time-to-live in seconds. Uses default_ttl if None.

        Returns:
            The cached or freshly computed value.
        """
        cached = await self.get(key)
        if cached is not None:
            return cached

        logger.debug("cache_miss_computing", key=key)
        try:
            value = await factory()
        except Exception as exc:
            logger.error(
                "cache_factory_failed",
                key=key,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

        await self.set(key, value, ttl)
        return value

    # ── Pattern Invalidation ───────────────────────────────────────────────────────

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all cache entries matching a glob pattern.

        Uses SCAN internally to avoid blocking Redis with KEYS.

        Args:
            pattern: Glob-style pattern (e.g. "company:*", "lead:*").

        Returns:
            Number of keys deleted.
        """
        deleted_count = 0
        cursor: int | None = 0
        try:
            while cursor is not None:
                cursor, keys = await self.client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    deleted = await self.client.delete(*keys)
                    deleted_count += deleted
            if deleted_count > 0:
                logger.info("cache_pattern_invalidated", pattern=pattern, keys_deleted=deleted_count)
            return deleted_count
        except Exception as exc:
            logger.warning("cache_pattern_invalidation_failed", pattern=pattern, error=str(exc))
            return deleted_count

    # ── Company-Specific Helpers ───────────────────────────────────────────────────

    async def get_company_cache(self, company_name: str) -> dict[str, Any] | None:
        """Retrieve cached company data by company name.

        Args:
            company_name: Company name to look up.

        Returns:
            Cached company data dict if found, None otherwise.
        """
        return await self.get(f"company:{company_name}")

    async def set_company_cache(self, company_name: str, data: dict[str, Any], ttl: int = 86400) -> bool:
        """Cache company data with a 24-hour TTL.

        Args:
            company_name: Company name used as cache key.
            data: Company data dict to cache.
            ttl: Time-to-live in seconds (default 86400 = 24 hours).

        Returns:
            True if the operation succeeded.
        """
        return await self.set(f"company:{company_name}", data, ttl)

    # ── Hit-Rate Tracking ─────────────────────────────────────────────────────────

    async def _record_hit(self, key: str) -> None:
        """Record a cache hit for observation."""
        try:
            await self.client.incr("cache_stats:hits")
        except Exception:
            pass

    async def _record_miss(self, key: str) -> None:
        """Record a cache miss for observation."""
        try:
            await self.client.incr("cache_stats:misses")
        except Exception:
            pass

    async def get_stats(self) -> dict[str, Any]:
        """Retrieve cache hit/miss statistics.

        Returns:
            Dict with 'hits', 'misses', 'total', and 'hit_rate' fields.
        """
        try:
            hits = int(await self.client.get("cache_stats:hits") or 0)
            misses = int(await self.client.get("cache_stats:misses") or 0)
            total = hits + misses
            hit_rate = round(hits / total, 4) if total > 0 else 0.0
            return {
                "hits": hits,
                "misses": misses,
                "total": total,
                "hit_rate": hit_rate,
            }
        except Exception as exc:
            logger.warning("cache_stats_fetch_failed", error=str(exc))
            return {"hits": 0, "misses": 0, "total": 0, "hit_rate": 0.0}

    async def reset_stats(self) -> None:
        """Reset hit-rate tracking counters."""
        try:
            await self.client.delete("cache_stats:hits", "cache_stats:misses")
            logger.info("cache_stats_reset")
        except Exception as exc:
            logger.warning("cache_stats_reset_failed", error=str(exc))
