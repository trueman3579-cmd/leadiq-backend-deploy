"""
collectors/freejobalert.py — FreeJobAlert scraper.

Government job alert platform: https://www.freejobalert.com/
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

FREEJOBALERT_BASE_URL = "https://www.freejobalert.com"


class FreeJobAlertCollector(BaseCollector):
    source = "freejobalert"

    def __init__(self, max_pages: int = 5):
        self._max_pages = max_pages

    async def collect(self) -> list[RawPost]:
        all_posts: list[RawPost] = []
        for page in range(1, self._max_pages + 1):
            try:
                posts = await self._scrape_page(page)
                all_posts.extend(posts)
                logger.info("freejobalert_page_complete", page=page, count=len(posts))
            except Exception as e:
                logger.warning("freejobalert_page_failed", page=page, error=str(e))
        logger.info("FreeJobAlertCollector fetched %d posts", len(all_posts))
        return all_posts

    async def _scrape_page(self, page: int) -> list[RawPost]:
        url = f"{FREEJOBALERT_BASE_URL}/page/{page}/" if page > 1 else FREEJOBALERT_BASE_URL
        result = await self._adapter.fetch(url)
        if not result.is_success():
            logger.warning("freejobalert_fetch_failed", url=url, status=result.status, error=result.error)
            return []

        soup = BeautifulSoup(result.data.get("text", ""), "html.parser")
        entries = soup.select(
            "div.post, article[class*='post'], div[class*='entry'], "
            "div[class*='job'], h2 a, h3 a"
        )

        posts = []
        for entry in entries:
            parsed = self._parse_entry(entry)
            if parsed:
                posts.append(parsed)
        return posts

    def _parse_entry(self, entry: Any) -> RawPost | None:
        try:
            link_el = entry.select_one("a")
            title_el = entry.select_one(
                "h2[class*='title'], h3[class*='title'], strong, "
                "[class*='heading'], [class*='title']"
            )
            desc_el = entry.select_one(
                "div[class*='desc'], p, span[class*='detail'], "
                "[class*='content']"
            )

            title = title_el.get_text(strip=True) if title_el else ""
            if not title and link_el:
                title = link_el.get_text(strip=True)
            if not title:
                return None

            description = desc_el.get_text(strip=True) if desc_el else ""

            href = ""
            if link_el and hasattr(link_el, "get"):
                href = link_el.get("href") or ""
            link = (
                f"{FREEJOBALERT_BASE_URL}{href}"
                if href and href.startswith("/")
                else href
            )

            external_id = self._extract_id(link or title)

            return RawPost(
                source=self.source,
                external_id=external_id,
                url=link,
                title=title,
                body=description or title,
                author="FreeJobAlert",
                score=0,
                raw_meta={
                    "category": "government_job",
                    "post_type": "alert",
                },
            )

        except Exception as exc:
            logger.warning("freejobalert_entry_parse_failed", error=str(exc))
            return None

    @staticmethod
    def _extract_id(text: str) -> str:
        match = re.search(r"/([^/?]+)\.html", text)
        if match:
            return match.group(1)
        match = re.search(r"/latest-jobs/([^/?]+)", text)
        if match:
            return match.group(1)
        return hashlib.md5(text.encode()).hexdigest()[:12]
