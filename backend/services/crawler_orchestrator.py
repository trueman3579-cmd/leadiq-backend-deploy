"""
backend/services/crawler_orchestrator.py — Central orchestrator for all crawlers.
Runs selected crawlers, aggregates results, and provides status tracking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.crawlers.base import CrawlResult

logger = logging.getLogger(__name__)

CRAWLER_MAP: dict[str, str] = {
    "schemes": "backend.services.crawlers.govt_schemes_crawler.GovtSchemesCrawler",
    "funding": "backend.services.crawlers.funding_crawler.FundingCrawler",
    "jobs": "backend.services.crawlers.jobs_crawler.JobsCrawler",
}


@dataclass
class OrchestratorRun:
    """Result of a full orchestrator run."""
    runs: dict[str, CrawlResult] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    @property
    def total_collected(self) -> int:
        return sum(r.items_collected for r in self.runs.values())

    @property
    def total_persisted(self) -> int:
        return sum(r.items_persisted for r in self.runs.values())

    @property
    def all_succeeded(self) -> bool:
        return all(r.status in ("success", "partial") for r in self.runs.values())


def _import_crawler(dotted_path: str):
    """Lazy-import a crawler class from its dotted path."""
    import importlib
    mod_path, _, cls_name = dotted_path.rpartition(".")
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


class CrawlerOrchestrator:
    """Orchestrate crawler runs with result aggregation."""

    def __init__(self) -> None:
        self._last_run: OrchestratorRun | None = None
        self._run_count = 0

    @property
    def last_run(self) -> OrchestratorRun | None:
        return self._last_run

    async def run_all(self, session: AsyncSession) -> OrchestratorRun:
        """Run all registered crawlers in sequence."""
        return await self._run(["schemes", "funding", "jobs"], session)

    async def run_schemes(self, session: AsyncSession) -> OrchestratorRun:
        return await self._run(["schemes"], session)

    async def run_funding(self, session: AsyncSession) -> OrchestratorRun:
        return await self._run(["funding"], session)

    async def run_jobs(self, session: AsyncSession) -> OrchestratorRun:
        return await self._run(["jobs"], session)

    async def _run(self, crawler_names: list[str], session: AsyncSession) -> OrchestratorRun:
        run = OrchestratorRun()

        for name in crawler_names:
            dotted_path = CRAWLER_MAP.get(name)
            if not dotted_path:
                logger.warning("Unknown crawler: %s", name)
                continue

            try:
                crawler_cls = _import_crawler(dotted_path)
                crawler = crawler_cls()
                result = await crawler.crawl(session)
                run.runs[name] = result
                logger.info(
                    "crawler_complete",
                    crawler=name,
                    status=result.status,
                    collected=result.items_collected,
                    persisted=result.items_persisted,
                )
            except Exception as exc:
                run.runs[name] = CrawlResult(
                    source=name,
                    status="failed",
                    errors=[str(exc)],
                )
                logger.error("crawler_crash", crawler=name, error=str(exc))

        run.finished_at = datetime.now(UTC)
        self._last_run = run
        self._run_count += 1
        return run