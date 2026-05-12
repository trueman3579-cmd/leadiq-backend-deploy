"""
workers/rate_limiter.py — Token bucket per Gemini model, stored in Redis.
Prevents 429s by tracking requests-per-minute and tokens-per-day.

Usage:
    limiter = GeminiRateLimiter(redis_client)
    async with limiter.acquire(model="gemini-2.0-flash", tokens_estimate=1000):
        response = await model.generate(...)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Gemini 2.0 Flash limits (per-minute)
MODEL_LIMITS: dict[str, dict[str, int]] = {
    "gemini-2.0-flash": {
        "rpm": 15,          # requests per minute (free tier)
        "tpm": 1_000_000,   # tokens per minute
        "rpd": 1_500,       # requests per day
    },
    "gemini-1.5-pro": {
        "rpm": 2,
        "tpm": 32_000,
        "rpd": 50,
    },
}


class GeminiRateLimiter:
    def __init__(self, client: aioredis.Redis) -> None:
        self._r = client

    def _rpm_key(self, model: str) -> str:
        minute = int(time.time() // 60)
        return f"leadiq:rl:{model}:rpm:{minute}"

    def _rpd_key(self, model: str) -> str:
        from datetime import date
        return f"leadiq:rl:{model}:rpd:{date.today().isoformat()}"

    async def check_and_increment(self, model: str) -> bool:
        """Return True if request is allowed; False if rate-limited."""
        limits = MODEL_LIMITS.get(model, MODEL_LIMITS["gemini-2.0-flash"])
        rpm_key = self._rpm_key(model)
        rpd_key = self._rpd_key(model)

        pipe = self._r.pipeline()
        pipe.incr(rpm_key)
        pipe.expire(rpm_key, 60)
        pipe.incr(rpd_key)
        pipe.expire(rpd_key, 86400)
        results = await pipe.execute()

        current_rpm, _, current_rpd, _ = results

        if current_rpm > limits["rpm"]:
            logger.warning("Rate limited: %s exceeded %d RPM", model, limits["rpm"])
            # Undo the increment
            await self._r.decr(rpm_key)
            await self._r.decr(rpd_key)
            return False

        if current_rpd > limits["rpd"]:
            logger.warning("Rate limited: %s exceeded %d RPD", model, limits["rpd"])
            await self._r.decr(rpd_key)
            return False

        return True

    @asynccontextmanager
    async def acquire(
        self, model: str, tokens_estimate: int = 500, max_wait_seconds: float = 30.0
    ) -> AsyncGenerator[None, None]:
        """Context manager that waits for a rate limit slot or raises TimeoutError."""
        deadline = time.monotonic() + max_wait_seconds
        while True:
            if await self.check_and_increment(model):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"GeminiRateLimiter: Could not acquire slot for {model} within {max_wait_seconds}s"
                )
            wait = min(5.0, remaining)
            logger.info("Rate limit hit for %s — waiting %.1fs", model, wait)
            await asyncio.sleep(wait)
        yield
