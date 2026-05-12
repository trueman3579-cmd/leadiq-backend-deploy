"""
backend/actors/naukri_actor.py — Naukri.com worker actor.

Can run standalone (``async run()``) or be invoked from a Celery task.
Follows the same pattern as GitHub/Telegram actors in workers/actors.py.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.collectors.base import RawPost
from backend.collectors.naukri import NaukriCollector

logger = logging.getLogger(__name__)


class NaukriActor:
    """Worker actor that wraps NaukriCollector for pipeline integration.

    Usage::

        actor = NaukriActor(keywords=[...], locations=[...])
        results: list[RawPost] = await actor.run()
    """

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_results: int = 100,
    ) -> None:
        self._keywords = keywords
        self._locations = locations
        self._max_results = max_results

    async def run(self) -> list[RawPost]:
        """Collect jobs from Naukri.com and return RawPost list."""
        collector = NaukriCollector(
            keywords=self._keywords,
            locations=self._locations,
            max_results_per_search=self._max_results,
        )
        results = await collector.collect()
        logger.info(
            "naukri_actor_run_complete",
            count=len(results),
        )
        return results

    async def run_and_publish(self, stream_name: str) -> dict[str, Any]:
        """Collect jobs and publish each one to a Redis stream.

        Args:
            stream_name: Redis stream name (e.g. ``lead:collected``).

        Returns:
            Dict with ``count`` and ``status`` keys.
        """
        from backend.shared.stream import redis_stream

        results = await self.run()
        published = 0
        for post in results:
            await redis_stream.publish(stream_name, post.to_stream_payload())
            published += 1

        logger.info("naukri_actor_published", count=published, stream=stream_name)
        return {"status": "ok", "count": published}


# ── Celery task (lazy-registered) ───────────────────────────────────────────

# This function follows the pattern in backend/workers/actors.py where
# tasks are decorated dynamically after the celery_app is available.
def naukri_task_factory(celery_app: Any):
    """Create and return a Celery task for Naukri collection.

    Call from ``setup_actors()`` after the celery_app is defined.
    """

    @celery_app.task(
        bind=True,
        name="actors.collect_naukri",
        max_retries=2,
        default_retry_delay=60,
        soft_time_limit=600,
        time_limit=720,
    )
    def collect_naukri_task(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Celery task: collect Naukri jobs and publish to pipeline stream."""
        from backend.services.feature_flags import is_actor_enabled

        if not is_actor_enabled("naukri"):
            logger.info("naukri_actor_disabled")
            return {"status": "disabled"}

        import asyncio

        async def _run() -> dict[str, Any]:
            from backend.shared.config import settings

            actor = NaukriActor(keywords=keywords, locations=locations)
            return await actor.run_and_publish(settings.STREAM_COLLECTED)

        try:
            return asyncio.run(_run())
        except Exception as exc:
            logger.error("collect_naukri_failed", error=str(exc))
            raise self.retry(exc=exc) from exc

    return collect_naukri_task
