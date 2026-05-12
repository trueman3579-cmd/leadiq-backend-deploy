"""
shared/deduper.py — Content deduplication using SHA-256 + Redis SET.
PostDeduplicator.is_duplicate(text) → bool
  - Hashes the canonical text representation
  - Checks Redis SET for existing hash (O(1))
  - On miss, adds to SET so the next call for the same content returns True

Usage:
  deduper = PostDeduplicator(redis_client)
  if not await deduper.is_duplicate(post.body):
      await process(post)
"""
from __future__ import annotations

import hashlib

import redis.asyncio as aioredis


DEDUP_KEY = "leadiq:dedup:hashes"
DEDUP_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


class PostDeduplicator:
    def __init__(self, client: aioredis.Redis) -> None:
        self._r = client

    @staticmethod
    def hash(text: str) -> str:
        """Return SHA-256 hex digest of the canonical text."""
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()

    async def is_duplicate(self, text: str) -> bool:
        """Return True if this content has been seen before.
        Side-effect: marks content as seen if it wasn't already."""
        h = self.hash(text)
        added = await self._r.sadd(DEDUP_KEY, h)
        # SADD returns 1 if field is new, 0 if it already existed
        if added == 1:
            # Refresh TTL on each new insertion
            await self._r.expire(DEDUP_KEY, DEDUP_TTL_SECONDS)
            return False
        return True

    async def reset(self) -> None:
        """Clear the dedup SET — use only in tests or manual resets."""
        await self._r.delete(DEDUP_KEY)
