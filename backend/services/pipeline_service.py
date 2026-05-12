"""
services/pipeline_service.py — Pipeline orchestration logic.

Business logic that was previously inline in API routes.
Keeps routes thin and delegates all orchestration here.
"""
from __future__ import annotations

import asyncio
import structlog

from backend.api.schemas import TriggerResponse
from backend.collectors.reddit import RedditCollector
from backend.collectors.hn import HNCollector
from backend.shared.config import settings
from backend.shared.stream import redis_stream

logger = structlog.get_logger(__name__)


async def trigger_collection() -> TriggerResponse:
    """Trigger the lead collection pipeline via Celery or direct async fallback."""
    try:
        from backend.workers.pipeline import collect_and_publish
        task = collect_and_publish.delay()
        return TriggerResponse(
            status="queued",
            message="Collection pipeline started",
            task_id=task.id,
        )
    except Exception:
        logger.warning("celery_unavailable_fallback_to_direct")
        asyncio.create_task(_quick_collect())
        return TriggerResponse(
            status="running",
            message="Background collection started (no Celery)",
        )


async def _quick_collect() -> None:
    """Direct async collection when Celery is unavailable."""
    await redis_stream.connect()
    for Collector in (RedditCollector, HNCollector):
        try:
            posts = await Collector().collect()  # type: ignore
            for post in posts:
                await redis_stream.publish(
                    settings.STREAM_COLLECTED, post.to_stream_payload()
                )
        except Exception as exc:
            logger.error("direct_collect_failed", collector=Collector.__name__, error=str(exc))


async def trigger_analysis() -> TriggerResponse:
    """Trigger the AI analysis pipeline via Celery or direct async fallback."""
    try:
        from backend.workers.pipeline import run_analysis_consumer
        task = run_analysis_consumer.delay()
        return TriggerResponse(
            status="queued",
            message="AI analysis pipeline started",
            task_id=task.id,
        )
    except Exception:
        logger.warning("celery_unavailable_fallback_to_direct")
        from backend.workers.analyzer import run_analyzer
        asyncio.create_task(run_analyzer())
        return TriggerResponse(
            status="running",
            message="AI analysis started in background (no Celery)",
        )
