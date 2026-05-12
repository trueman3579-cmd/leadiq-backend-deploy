"""
backend/workers/__init__.py — Celery workers module.

This module exports all worker tasks for Celery autodiscovery.
"""
from backend.workers.pipeline import (
    collect_and_publish,
    run_analysis_consumer,
    run_scoring_consumer,
    persist_scored_leads,
    dedup_lead,
    refresh_intent_signals,
    compute_daily_metrics,
    process_dlq_retries,
)

from backend.workers.actors import (
    collect_github_task,
    search_github_india_task,
    monitor_telegram_task,
)

# Register actor tasks with celery_app
from backend.workers.pipeline import celery_app

# Setup actors after celery_app is defined
setup_actors_imported = False
try:
    from backend.workers.actors import setup_actors

    setup_actors(celery_app)
    setup_actors_imported = True
except Exception:
    pass

__all__ = [
    # Pipeline tasks
    "collect_and_publish",
    "run_analysis_consumer",
    "run_scoring_consumer",
    "persist_scored_leads",
    "dedup_lead",
    "refresh_intent_signals",
    "compute_daily_metrics",
    "process_dlq_retries",
    # Actor tasks
    "collect_github_task",
    "search_github_india_task",
    "monitor_telegram_task",
]
