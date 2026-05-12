"""
backend/services/crawlers/funding_crawler.py
Aggregates funding signals from multiple web sources and persists to FundingEvent table.
Sources: YourStory RSS, Inc42, Entrackr, Crunchbase (via httpx)
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.repository import FundingEventRepo
from backend.services.crawlers.base import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)


# ── Source Config ────────────────────────────────────────────────────────────

FUNDING_SOURCES = [
    {
        "name": "yourstory",
        "url": "https://yourstory.com/feed",
        "type": "rss",
        "trust": 7.0,
    },
    {
        "name": "inc42",
        "url": "https://inc42.com/feed/",
        "type": "rss",
        "trust": 7.0,
    },
    {
        "name": "entrackr",
        "url": "https://entrackr.com/feed/",
        "type": "rss",
        "trust": 7.0,
    },
    {
        "name": "crunchbase",
        "url": "https://www.crunchbase.com/discover/funding_rounds",
        "type": "bookmarklet",
        "trust": 5.0,
    },
]

# ── Crawler ─────────────────────────────────────────────────────────────


class FundingCrawler(BaseCrawler):
    """Crawl funding sources → FundingEvent table."""

    source = "funding"

    async def crawl(self, session: AsyncSession) -> CrawlResult:
        result = CrawlResult(source=self.source)

        import aiohttp
        import feedparser

        repo = FundingEventRepo(session)
        persisted = 0
        collected = 0

        for source_cfg in FUNDING_SOURCES:
            try:
                if source_cfg["type"] == "rss":
                    items = await self._scrape_rss(source_cfg)
                elif source_cfg["type"] == "bookmarklet":
                    logger.info("Browser fetch needed for %s — use LeadIQ bookmarklet", source_cfg["name"])
                    items = []
                else:
                    continue

                collected += len(items)

                for item in items:
                    try:
                        await repo.upsert(item)
                        persisted += 1
                    except Exception as exc:
                        result.errors.append(
                            f"Upsert failed for {item.get('company_name', '?')}: {exc}"
                        )

            except Exception as exc:
                result.errors.append(f"Source {source_cfg['name']} failed: {exc}")
                logger.warning("funding_source_failed", source=source_cfg["name"], error=str(exc))

        result.items_collected = collected
        result.items_persisted = persisted
        result.status = "success" if persisted > 0 else "partial"
        result.finished_at = datetime.now(UTC)
        return result

    async def _scrape_rss(self, cfg: dict) -> list[dict]:
        """Parse RSS feed from a funding news source."""
        import aiohttp
        import feedparser

        items = []
        async with aiohttp.ClientSession() as session:
            async with session.get(cfg["url"], timeout=30) as resp:
                if resp.status != 200:
                    return items
                text = await resp.text()

        feed = feedparser.parse(text)
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            body = entry.get("summary", entry.get("description", ""))
            text_content = f"{title} {body}"

            funding_keywords = [
                "raised", "funding", "series", "seed", "million",
                "lakh", "crore", "investment", "round",
            ]
            if not any(kw in text_content.lower() for kw in funding_keywords):
                continue

            company = self._extract_company(text_content)
            amount = self._extract_amount(text_content)
            round_type = self._extract_round_type(text_content)
            link = entry.get("link", cfg["url"])

            items.append({
                "company_name": company or "Unknown",
                "amount": amount,
                "round_type": round_type,
                "date": datetime.now(UTC),
                "source": cfg["name"],
                "location": "India",
                "industry": None,
                "trust_score": cfg["trust"],
                "is_verified": False,
                "raw_excerpt": text_content[:500],
            })

        return items

    async def _scrape_bookmarklet(self, cfg: dict) -> list[dict]:
        """Browser-based fetch not available in deploy mode — use LeadIQ bookmarklet."""
        logger.info("Browser fetch needed for %s — use LeadIQ bookmarklet", cfg["name"])
        return []

    # ── Extraction Helpers ────────────────────────────────────────────────

    @staticmethod
    def _extract_company(text: str) -> str | None:
        import re
        patterns = [
            r"^([A-Z][A-Za-z0-9\s&.]+?)\s+(?:raises?|secures?|gets|lands|closes)",
            r"([A-Z][A-Za-z0-9\s&.]+?)\s+(?:announces?|closes?)\s+(?:funding|series)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_amount(text: str) -> str | None:
        import re
        patterns = [
            r"\$([\d,.]+)\s*(M|B|K|million|billion)",
            r"₹([\d,.]+)\s*(Cr|crore|L|lakh|M|mn)?",
            r"([\d,.]+)\s*(million|billion|crore|lakh)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None

    @staticmethod
    def _extract_round_type(text: str) -> str | None:
        import re
        patterns = [
            r"(Series\s+[A-F]\s*(?:Extension)?)",
            r"(Pre-[Ss]eed)",
            r"(Seed\s+(?:Round|Funding)?)",
            r"(Bridge\s+Round)",
            r"(Growth\s+Round)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None