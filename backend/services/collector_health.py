"""
collector_health.py — Collector health monitoring dashboard.

Provides a health-check endpoint and CLI tool to verify all collectors
are working. Runs each collector in dry-run mode (fetch + parse only,
skips dedup/publish) and reports status.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CollectorHealth:
    source: str
    healthy: bool = False
    posts: int = 0
    error: str = ""
    response_time_ms: float = 0.0
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "healthy": self.healthy,
            "posts": self.posts,
            "error": self.error,
            "response_time_ms": round(self.response_time_ms, 1),
            "enabled": self.enabled,
        }


async def check_collector(source: str) -> CollectorHealth:
    from backend.ingestion.collectors import get_collector_by_source
    health = CollectorHealth(source=source)

    try:
        cls = get_collector_by_source(source)
        collector = cls()

        if not collector.enabled:
            health.healthy = True
            health.error = "disabled_by_config"
            return health

        start = time.monotonic()
        try:
            posts = await asyncio.wait_for(collector.collect(), timeout=30.0)
            elapsed = (time.monotonic() - start) * 1000
            health.response_time_ms = elapsed
            health.posts = len(posts)
            health.healthy = len(posts) > 0
            if not health.healthy:
                health.error = "zero_posts"
        except asyncio.TimeoutError:
            health.error = "timeout"
        except Exception as e:
            health.error = str(e)[:200]

    except Exception as e:
        health.error = f"instantiation_error: {e}"

    return health


async def check_all_collectors() -> list[dict]:
    from backend.ingestion.collectors import get_source_names
    sources = get_source_names()
    results = []
    for source in sources:
        health = await check_collector(source)
        results.append(health.to_dict())
        status = "OK" if health.healthy else "FAIL"
        logger.info("health_check", source=source, status=status, posts=health.posts, error=health.error or "")
    return results


def format_health_table(results: list[dict]) -> str:
    lines = []
    lines.append(f"{'Source':25s} {'Status':8s} {'Posts':6s} {'Time(ms)':10s} Error")
    lines.append("-" * 80)
    for r in results:
        status = "OK" if r["healthy"] else "FAIL"
        error = r["error"][:40] if r["error"] else ""
        lines.append(
            f"{r['source']:25s} {status:8s} {str(r['posts']):6s} {str(round(r['response_time_ms'], 1)):10s} {error}"
        )
    ok = sum(1 for r in results if r["healthy"])
    lines.append("-" * 80)
    lines.append(f"Total: {len(results)} | Healthy: {ok} | Failing: {len(results) - ok}")
    return "\n".join(lines)


if __name__ == "__main__":
    results = asyncio.run(check_all_collectors())
    print(format_health_table(results))
