"""
backend/workers/actors.py — Celery tasks for data collection actors.

This module contains all actor tasks (GitHub, Telegram, etc.) that feed
into the existing pipeline. These are COLLECTORS - they produce raw data
to the pipeline's Redis stream, which then goes through analyze/score/persist.

Separation of concerns: pipeline.py handles the pipeline flow, actors.py
handles data collection from external sources.

To avoid circular imports, actors.py is imported AFTER pipeline.py defines
celery_app. We use a module-level lazy import pattern.
"""
from __future__ import annotations

import asyncio
import structlog
from typing import Any

from backend.shared.config import settings
from backend.shared.stream import redis_stream
from backend.services.feature_flags import is_actor_enabled

logger = structlog.get_logger(__name__)

# ─── Lazy celery_app import to avoid circular dependency ────────────────────
# When this module is imported after pipeline.py defines celery_app,
# the tasks will be decorated with the actual celery_app instance.
_celery_app: Any = None


def get_celery_app() -> Any:
    """Get the celery app - imports lazily to avoid circular imports."""
    global _celery_app
    if _celery_app is None:
        from backend.workers.pipeline import celery_app

        _celery_app = celery_app
    return _celery_app


def _decorate_task(task_func):
    """Decorator factory that lazily applies the celery_app decorator."""
    import functools

    @functools.wraps(task_func)
    def wrapper(*args, **kwargs):
        # At import time, the actual decorator will be applied
        # when celery_app is available
        return task_func(*args, **kwargs)

    return wrapper


# ── Actor Tasks ───────────────────────────────────────────────────────────────

# These tasks will be decorated with the actual celery_app when it's available
# The @celery_app.task() syntax will fail if celery_app is None, so we
# register them dynamically after pipeline.py sets the app


def _register_actor_tasks(celery_app_instance):
    """Register all actor tasks with the given celery_app instance."""
    global _celery_app
    _celery_app = celery_app_instance

    # Apply decorators dynamically
    @celery_app_instance.task(
        bind=True,
        name="actors.collect_github",
        max_retries=2,
        default_retry_delay=30,
        soft_time_limit=90,
        time_limit=120,
    )
    def collect_github_task(self, username: str):
        """Collect one GitHub profile → enqueue to pipeline stream."""
        if not is_actor_enabled("github"):
            logger.info("github_actor_disabled")
            return {"status": "disabled"}

        async def _run() -> dict[str, Any]:
            from backend.workers.actors.github import GitHubCollector

            collector = GitHubCollector(redis_stream._r)
            return await collector.collect_profile(username, settings.STREAM_COLLECTED)

        try:
            return asyncio.run(_run())
        except Exception as exc:
            logger.error("collect_github_failed", username=username, error=str(exc))
            raise self.retry(exc=exc) from exc

    @celery_app_instance.task(
        bind=True,
        name="actors.search_github_india",
        max_retries=1,
        soft_time_limit=300,
        time_limit=360,
    )
    def search_github_india_task(self, tech_stack: list[str], location: str = "India"):
        """Search GitHub for Indian founders → enqueue collect_github per result."""
        if not is_actor_enabled("github"):
            logger.info("github_actor_disabled")
            return {"status": "disabled"}

        async def _run() -> dict[str, Any]:
            from backend.workers.actors.github import GitHubCollector

            collector = GitHubCollector(redis_stream._r)
            usernames = []
            for tech in tech_stack[:3]:  # max 3 tech terms
                results = await collector.search_india_founders(tech, location)
                usernames.extend(results)

            usernames = list(set(usernames))[:50]  # deduplicate, cap at 50
            for username in usernames:
                collect_github_task.delay(username)
            return {"status": "queued", "count": len(usernames)}

        try:
            return asyncio.run(_run())
        except Exception as exc:
            logger.error("search_github_india_failed", error=str(exc))
            raise self.retry(exc=exc) from exc

    @celery_app_instance.task(
        bind=True,
        name="actors.monitor_telegram",
        max_retries=1,
        soft_time_limit=600,
        time_limit=720,
    )
    def monitor_telegram_task(self, channels: list[str] | None = None):
        """Monitor Telegram channels for funding/hiring signals."""
        if not is_actor_enabled("telegram"):
            logger.info("telegram_actor_disabled")
            return {"status": "disabled"}

        async def _run() -> dict[str, Any]:
            from backend.workers.actors.telegram import TelegramCollector

            collector = TelegramCollector(redis_stream._r)
            if channels:
                collector.channels = channels
            return await collector.run_all(settings.STREAM_COLLECTED)

        try:
            return asyncio.run(_run())
        except Exception as exc:
            logger.error("monitor_telegram_failed", error=str(exc))
            raise self.retry(exc=exc) from exc

    # Register the tasks in the task router
    from backend.workers.dlq import TASK_ROUTER

    TASK_ROUTER["actors.collect_github"] = lambda a, k: collect_github_task.apply_async(
        args=a, kwargs=k
    )
    TASK_ROUTER["actors.search_github_india"] = (
        lambda a, k: search_github_india_task.apply_async(args=a, kwargs=k)
    )
    TASK_ROUTER["actors.monitor_telegram"] = (
        lambda a, k: monitor_telegram_task.apply_async(args=a, kwargs=k)
    )

    # Add to beat schedule
    celery_app_instance.conf.beat_schedule.update(
        {
            "telegram-monitor-every-2-hours": {
                "task": "actors.monitor_telegram",
                "schedule": 7200.0,  # 2 hours
                "options": {"queue": "monitoring"},
            }
        }
    )

    return collect_github_task, search_github_india_task, monitor_telegram_task


# Make these available at module level for manual registration
collect_github_task = None
search_github_india_task = None
monitor_telegram_task = None


def setup_actors(celery_app_instance):
    """Setup actor tasks with the celery app - call after pipeline.py creates the app."""
    global collect_github_task, search_github_india_task, monitor_telegram_task

    (collect_github_task, search_github_india_task, monitor_telegram_task) = (
        _register_actor_tasks(celery_app_instance)
    )
