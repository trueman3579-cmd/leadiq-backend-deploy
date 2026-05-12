"""
source_metrics.py — Source Quality Metrics Tracker (Day 11)
Tracks per-source qualification rate (% of posts classified as opportunity).
Sources below QUALIFICATION_THRESHOLD get flagged for disabling.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, UTC
from pathlib import Path

import redis.asyncio as aioredis

# Canonical source list (used by health check and metrics tracking)
SOURCES = [
    "github", "hacker_news", "producthunt", "reddit", "stackoverflow",
    "twitter", "rss", "telegram", "linkedin", "indeed", "naukri",
    "internshala", "shine", "monster", "naukrigulf", "freshersworld",
    "hirist", "cutshort", "instahyre", "hirect", "weekday", "timesjobs",
    "foundit", "freejobalert", "iimjobs", "dpiit", "mca21", "msme",
    "government_schemes", "tracxn", "yourstory", "indiamart", "gem",
]

from backend.shared.config import settings

logger = logging.getLogger(__name__)

QUALIFICATION_THRESHOLD = float(os.getenv("SOURCE_QUALIFICATION_THRESHOLD", "0.15"))
AUDIT_FILE = Path(os.getenv("SOURCE_AUDIT_FILE", "source_audit.json"))
def _active_sources() -> list[str]:
    """Get active (non-hibernated) source names from the factory."""
    from backend.ingestion.collectors import get_source_names
    return get_source_names()

_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


def _total_key(source: str, day: date | None = None) -> str:
    day = day or date.today()
    return f"source_metrics:{source}:total:{day.isoformat()}"


def _qualified_key(source: str, day: date | None = None) -> str:
    day = day or date.today()
    return f"source_metrics:{source}:qualified:{day.isoformat()}"


async def record_post(source: str, is_opportunity: bool) -> None:
    """Called after every classification. Records total + qualified counts with 30-day TTL."""
    if source not in _active_sources():
        return
    r = await _get_redis()
    pipe = r.pipeline()
    total_k = _total_key(source)
    qualified_k = _qualified_key(source)
    pipe.incr(total_k)
    pipe.expire(total_k, 86400 * 30)
    if is_opportunity:
        pipe.incr(qualified_k)
        pipe.expire(qualified_k, 86400 * 30)
    await pipe.execute()


async def get_qualification_rate(source: str, days: int = 7) -> dict:
    """Returns qualification rate for a source over the past N days."""
    r = await _get_redis()
    total = 0
    qualified = 0
    today = date.today()
    for i in range(days):
        day = today - timedelta(days=i)
        t = int(await r.get(_total_key(source, day)) or 0)
        q = int(await r.get(_qualified_key(source, day)) or 0)
        total += t
        qualified += q

    rate = (qualified / total) if total > 0 else None
    if total == 0:
        status = "no_data"
    elif rate is not None and rate >= QUALIFICATION_THRESHOLD * 2:
        status = "healthy"
    elif rate is not None and rate >= QUALIFICATION_THRESHOLD:
        status = "warning"
    else:
        status = "cut"

    return {
        "source": source, "total": total, "qualified": qualified,
        "rate": round(rate, 4) if rate is not None else None,
        "rate_pct": round(rate * 100, 1) if rate is not None else None,
        "threshold_pct": QUALIFICATION_THRESHOLD * 100, "days": days, "status": status,
    }


async def get_all_source_metrics(days: int = 7) -> list[dict]:
    """Returns qualification metrics for all sources."""
    return [await get_qualification_rate(s, days) for s in SOURCES]


async def run_source_audit(days: int = 7) -> dict:
    """Runs a full source audit and saves to source_audit.json."""
    metrics = await get_all_source_metrics(days)
    cut_sources = [m["source"] for m in metrics if m["status"] == "cut"]
    warning_sources = [m["source"] for m in metrics if m["status"] == "warning"]
    healthy_sources = [m["source"] for m in metrics if m["status"] == "healthy"]

    audit = {
        "audit_date": datetime.now(UTC).isoformat(),
        "window_days": days, "threshold_pct": QUALIFICATION_THRESHOLD * 100,
        "sources": metrics,
        "summary": {
            "healthy": healthy_sources, "warning": warning_sources,
            "cut_recommended": cut_sources, "total_sources": len(SOURCES),
            "sources_to_disable": len(cut_sources),
        },
        "action_required": len(cut_sources) > 0,
    }

    existing = []
    if AUDIT_FILE.exists():
        try:
            existing = json.loads(AUDIT_FILE.read_text())
            if not isinstance(existing, list):
                existing = [existing]
        except (json.JSONDecodeError, FileNotFoundError):
            existing = []
    existing.append(audit)
    AUDIT_FILE.write_text(json.dumps(existing, indent=2))

    logger.info("source_audit: healthy=%d cut=%d", len(healthy_sources), len(cut_sources))
    return audit
