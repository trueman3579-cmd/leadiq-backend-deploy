"""
collectors/timesjobs.py — TimesJobs scraper.

India's leading recruitment platform: https://www.timesjobs.com/
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

TIMESJOBS_BASE_URL = "https://www.timesjobs.com"


class TimesJobsCollector(BaseCollector):
    source = "timesjobs"

    def __init__(self, keywords: list[str] | None = None, max_results: int = 50):
        self._keywords = keywords or ["software", "data", "developer"]
        self._max_results = max_results

    async def collect(self) -> list[RawPost]:
        all_jobs: list[RawPost] = []
        for keyword in self._keywords:
            try:
                jobs = await self._scrape(keyword)
                all_jobs.extend(jobs)
                logger.info("timesjobs_search_complete", keyword=keyword, jobs_found=len(jobs))
            except Exception as e:
                logger.warning("timesjobs_search_failed", keyword=keyword, error=str(e))
        logger.info("TimesJobsCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape(self, keyword: str) -> list[RawPost]:
        url = (
            f"{TIMESJOBS_BASE_URL}/candidate/job-search.html?"
            f"searchType=personalizedSearch&from=submit&"
            f"txtKeywords={keyword}&txtLocation=India"
        )
        result = await self._adapter.fetch(url)
        if not result.is_success():
            logger.warning("timesjobs_fetch_failed", url=url, status=result.status, error=result.error)
            return []

        soup = BeautifulSoup(result.data.get("text", ""), "html.parser")
        cards = soup.select(
            "div.job-bx, div[class*='job'], article[class*='job'], "
            "li[class*='job'], div[class*='card']"
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
                "h2[class*='title'], h3[class*='title'], a[class*='title'], "
                "strong a, [class*='jobTitle'], [class*='job-title'], header a"
            )
            company_el = card.select_one(
                "span[class*='company'], div[class*='company'], "
                "[class*='comp'], h3[class*='company']"
            )
            location_el = card.select_one(
                "span[class*='location'], div[class*='location'], "
                "li[class*='location'], [class*='loc']"
            )
            salary_el = card.select_one(
                "span[class*='salary'], div[class*='salary'], "
                "li[class*='salary'], [class*='sal'], [class*='package']"
            )
            desc_el = card.select_one(
                "div[class*='desc'], p[class*='desc'], "
                "[class*='description'], [class*='skill']"
            )
            link_el = card.select_one(
                "a[class*='title'], h2 a, h3 a, strong a, "
                "a[href*='/job/'], a[href*='/jobs/']"
            )

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else ""
            salary_text = salary_el.get_text(strip=True) if salary_el else ""
            description = desc_el.get_text(strip=True) if desc_el else ""

            href = ""
            if link_el and hasattr(link_el, "get"):
                href = link_el.get("href") or ""
            link = (
                f"{TIMESJOBS_BASE_URL}{href}"
                if href and href.startswith("/")
                else href
            )

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
            logger.warning("timesjobs_card_parse_failed", error=str(exc))
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
