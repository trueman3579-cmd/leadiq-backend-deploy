"""
ingestion/orchestrator.py — Main ingestion orchestration logic.

Handles the complete ingestion pipeline: collect, deduplicate, publish to streams.

Usage:
    from backend.ingestion.orchestrator import IngestionOrchestrator

    orchestrator = IngestionOrchestrator()
    result = await orchestrator.run_all()
"""
from __future__ import annotations

from typing import Any

from backend.shared.stream import redis_stream
from backend.shared.config import settings


class IngestionOrchestrator:
    """
    Orchestrates the complete lead ingestion pipeline.

    Coordinates collectors, deduplication, and Redis stream publishing.
    """

    def __init__(self) -> None:
        self._deduplicator = None  # type: Any | None
        self._redis_stream = redis_stream
        self._profile_mode = "b2b_sales"

    async def _init_deduplicator(self) -> None:
        """Initialize Redis deduplicator if not already done."""
        if self._deduplicator is None:
            from backend.shared.deduper import PostDeduplicator
            if not self._redis_stream._client:
                await self._redis_stream.connect()
            self._deduplicator = PostDeduplicator(self._redis_stream._r)

    async def run_all(self) -> dict[str, Any]:
        """
        Run complete ingestion: collect all sources, deduplicate, publish.

        Returns:
            Ingestion summary with counts
        """
        from celery.utils.log import get_task_logger
        logger = get_task_logger(__name__)

        await self._init_deduplicator()

        # Get configured collectors
        from backend.ingestion.collectors import get_collectors
        collectors = get_collectors(mode=self._profile_mode)

        # Run collection loop
        published = 0
        skipped = 0
        failed = 0

        for collector in collectors:
            try:
                posts = await collector.collect()
                logger.info("Collector %s returned %d posts", collector.source, len(posts))

                if len(posts) == 0:
                    logger.warning(
                        "Collector %s returned 0 posts — possible selector rot or site blocking",
                        collector.source,
                    )

                for post in posts:
                    # Check deduplication
                    content_hash = post.content_hash
                    if await self._deduplicator.is_duplicate(content_hash):
                        skipped += 1
                        continue

                    # Publish to stream
                    payload = post.to_stream_payload()
                    payload["mode"] = self._profile_mode
                    await self._redis_stream.publish(settings.STREAM_COLLECTED, payload)
                    published += 1

            except Exception as exc:
                logger.error("Collector %s failed: %s", collector.source, exc)
                failed += 1

        logger.info(
            "Ingestion complete: %d published, %d skipped, %d failed",
            published, skipped, failed
        )

        return {
            "published": published,
            "skipped": skipped,
            "failed": failed,
            "mode": self._profile_mode,
        }

    async def run_single_source(self, source: str) -> dict[str, Any]:
        """
        Run ingestion for a single source.

        Args:
            source: Source name (e.g., "reddit", "hn", "twitter")

        Returns:
            Ingestion summary
        """
        from backend.ingestion.collectors import get_collector_by_source

        collector_class = get_collector_by_source(source)
        collector = collector_class()

        await self._init_deduplicator()

        posts = await collector.collect()
        published = 0
        skipped = 0

        for post in posts:
            content_hash = post.content_hash
            if await self._deduplicator.is_duplicate(content_hash):
                skipped += 1
                continue

            payload = post.to_stream_payload()
            payload["mode"] = self._profile_mode
            await self._redis_stream.publish(settings.STREAM_COLLECTED, payload)
            published += 1

        return {
            "source": source,
            "published": published,
            "skipped": skipped,
        }


async def run_ingestion(mode: str = "b2b_sales") -> dict[str, Any]:
    """
    Convenience function to run full ingestion.

    Args:
        mode: Profile mode for collection

    Returns:
        Ingestion summary
    """
    orchestrator = IngestionOrchestrator()
    return await orchestrator.run_all()


__all__ = ["IngestionOrchestrator", "run_ingestion"]
