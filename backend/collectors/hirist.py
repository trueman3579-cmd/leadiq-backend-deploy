"""
collectors/hirist.py — Hirist tech job scraper.

India's tech-focused job platform: https://www.hirist.com/
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

HIRIST_BASE_URL = "https://www.hirist.com"


class HiristCollector(BaseCollector):
    source = "hirist"

    def __init__(self, keywords: list[str] | None = None, max_results: int = 50):
        self._keywords = keywords or ["software", "data", "developer"]
        self._max_results = max_results

    async def collect(self) -> list[RawPost]:
        all_jobs: list[RawPost] = []
        for keyword in self._keywords:
            try:
                jobs = await self._scrape(keyword)
                all_jobs.extend(jobs)
                logger.info("hirist_search_complete", keyword=keyword, jobs_found=len(jobs))
            except Exception as e:
                logger.warning("hirist_search_failed", keyword=keyword, error=str(e))
        logger.info("HiristCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape(self, keyword: str) -> list[RawPost]:
        url = f"{HIRIST_BASE_URL}/search/{keyword}"
        result = await self._adapter.fetch(url)
        if not result.is_success():
            logger.warning("hirist_fetch_failed", url=url, status=result.status, error=result.error)
            return []

        soup = BeautifulSoup(result.data.get("text", ""), "html.parser")
        cards = soup.select(
            "div.job-card, div[class*='job'], div[class*='card'], "
            "section[class*='job'], li[class*='job']"
        )

        posts = []
        for card in cards[:self._max_results]:
            parsed = self._parse_card(card)
            if parsed:
                posts.append(parsed)
        return posts

    def _parse_card(self, card: Any) -> RawPost | None:
        try:
            title_el = card.select_one(
                "h3[class*='title'], h2[class*='title'], a[class*='title'], "
                "[class*='jobTitle'], [class*='job-title']"
            )
            company_el = card.select_one(
                "span[class*='company'], div[class*='company'], "
                "[class*='comp'], [class*='employer']"
            )
            location_el = card.select_one(
                "span[class*='location'], div[class*='location'], [class*='loc']"
            )
            salary_el = card.select_one(
                "span[class*='salary'], div[class*='salary'], [class*='sal'], "
                "[class*='package']"
            )
            desc_el = card.select_one(
                "div[class*='desc'], p[class*='desc'], [class*='description'], "
                "[class*='skill'], [class*='tech']"
            )
            link_el = card.select_one(
                "a[class*='title'], a[href*='/job/'], a[href*='/jobs/']"
            )

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else ""
            salary_text = salary_el.get_text(strip=True) if salary_el else ""
            description = desc_el.get_text(strip=True) if desc_el else ""

            href = ""
            if link_el and hasattr(link_el, "get"):
                href = link_el.get("href") or ""
            link = f"{HIRIST_BASE_URL}{href}" if href and href.startswith("/") else href

            external_id = self._extract_id(link or href)

            return RawPost(
                source=self.source,
                external_id=external_id,
                url=link,
                title=title,
                body=description or f"Job at {company}. Location: {location}.",
                author=company,
                score=0,
                raw_meta={
                    "company_name": company,
                    "location": location,
                    "salary": salary_text,
                },
            )

        except Exception as exc:
            logger.warning("hirist_card_parse_failed", error=str(exc))
            return None

    @staticmethod
    def _extract_id(url_or_path: str) -> str:
        match = re.search(r"/job/([^/?]+)", url_or_path)
        if match:
            return match.group(1)
        match = re.search(r"job[_-]?id[=:](\w+)", url_or_path, re.IGNORECASE)
        if match:
            return match.group(1)
        return hashlib.md5(url_or_path.encode()).hexdigest()[:12]
