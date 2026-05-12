"""
backend/services/crawlers/govt_schemes_crawler.py
Crawls government scheme portals and persists to GovScheme table.
Sources: data.gov.in, startupindia.gov.in, msme.gov.in, sidbi.in, investindia.gov.in
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backend.collectors.government_schemes import GovernmentScraper
from backend.shared.repository import GovSchemeRepo
from backend.services.crawlers.base import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)


class GovtSchemesCrawler(BaseCrawler):
    """Crawl government scheme portals → GovScheme table."""

    source = "govt_schemes"

    def __init__(self) -> None:
        self._scraper = GovernmentScraper()

    async def crawl(self, session: AsyncSession) -> CrawlResult:
        result = CrawlResult(source=self.source)

        try:
            raw_schemes = await self._scraper.scrape_all()
            result.items_collected = len(raw_schemes)
        except Exception as exc:
            result.status = "failed"
            result.errors.append(f"Scrape failed: {exc}")
            logger.error("govt_schemes_scrape_failed", error=str(exc))
            return result

        repo = GovSchemeRepo(session)
        persisted = 0
        for scheme in raw_schemes:
            try:
                await repo.upsert({
                    "name": scheme.name,
                    "description": scheme.description,
                    "eligibility": scheme.eligibility,
                    "deadline": scheme.deadline,
                    "funding_amount": scheme.funding_amount,
                    "source_url": scheme.source_url,
                    "department": scheme.department,
                    "trust_score": scheme.trust_score,
                })
                persisted += 1
            except Exception as exc:
                result.errors.append(f"Failed to persist '{scheme.name[:50]}': {exc}")
                logger.warning("govt_scheme_upsert_failed", name=scheme.name, error=str(exc))

        result.items_persisted = persisted
        result.status = "success" if persisted > 0 else "partial"
        result.finished_at = __import__("datetime").datetime.utcnow()
        logger.info("govt_schemes_crawl_complete", collected=result.items_collected, persisted=persisted)
        return result