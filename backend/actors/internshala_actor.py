"""
backend/actors/internshala_actor.py — Internshala worker actor.

Can run standalone (``async run()``) or be invoked from a Celery task.
Follows the same pattern as GitHub/Telegram actors in workers/actors.py.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.collectors.base import RawPost
from backend.collectors.internshala import InternshalaCollector

logger = logging.getLogger(__name__)


class InternshalaActor:
    """Worker actor that wraps InternshalaCollector for pipeline integration.

    Usage::

        actor = InternshalaActor(categories=[...])
        results: list[RawPost] = await actor.run()
    """

    def __init__(
        self,
        categories: list[str] | None = None,
        max_pages: int = 10,
    ) -> None:
        self._categories = categories
        self._max_pages = max_pages

    async def run(self) -> list[RawPost]:
        """Collect internships from Internshala and return RawPost list."""
        collector = InternshalaCollector(
            categories=self._categories,
            max_pages=self._max_pages,
        )
        results = await collector.collect()
        logger.info(
            "internshala_actor_run_complete",
            count=len(results),
        )
        return results

    async def run_and_publish(self, stream_name: str) -> dict[str, Any]:
        """Collect internships and publish each one to a Redis stream.

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

        logger.info(
            "internshala_actor_published", count=published, stream=stream_name
        )
        return {"status": "ok", "count": published}


# ── Celery task (lazy-registered) ───────────────────────────────────────────

# This function follows the pattern in backend/workers/actors.py where
# tasks are decorated dynamically after the celery_app is available.
def internshala_task_factory(celery_app: Any):
    """Create and return a Celery task for Internshala collection.

    Call from ``setup_actors()`` after the celery_app is defined.
    """

    @celery_app.task(
        bind=True,
        name="actors.collect_internshala",
        max_retries=2,
        default_retry_delay=60,
        soft_time_limit=600,
        time_limit=720,
    )
    def collect_internshala_task(
        self,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Celery task: collect Internshala internships and publish to pipeline."""
        from backend.services.feature_flags import is_actor_enabled

        if not is_actor_enabled("internshala"):
            logger.info("internshala_actor_disabled")
            return {"status": "disabled"}

        import asyncio

        async def _run() -> dict[str, Any]:
            from backend.shared.config import settings

            actor = InternshalaActor(categories=categories)
            return await actor.run_and_publish(settings.STREAM_COLLECTED)

        try:
            return asyncio.run(_run())
        except Exception as exc:
            logger.error("collect_internshala_failed", error=str(exc))
            raise self.retry(exc=exc) from exc

    return collect_internshala_task
