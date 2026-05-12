"""
collectors/internshala.py — Internshala internship collector.

"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

BASE_URL = "https://internshala.com"


class InternshalaCollector(BaseCollector):
    source = "internshala"

    def __init__(self, keywords: list[str] | None = None, max_results: int = 50):
        self._keywords = keywords or ["computer-science", "web-development", "software-development"]
        self._max_results = max_results

    async def collect(self) -> list[RawPost]:
        all_jobs: list[RawPost] = []
        for keyword in self._keywords:
            try:
                jobs = await self._scrape(keyword)
                all_jobs.extend(jobs)
                logger.info("internshala_search_complete", keyword=keyword, jobs_found=len(jobs))
            except Exception as e:
                logger.warning("internshala_search_failed", keyword=keyword, error=str(e))
        logger.info("InternshalaCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape(self, keyword: str) -> list[RawPost]:
        url = f"{BASE_URL}/internships/{keyword}/"
        result = await self._adapter.fetch(url)
        if not result.is_success():
            logger.warning("internshala_fetch_failed", url=url, status=result.status, error=result.error)
            return []

        soup = BeautifulSoup(result.data.get("text", ""), "html.parser")
        cards = soup.select("div.individual_internship")
        posts = []
        for card in cards[:self._max_results]:
            parsed = self._parse_card(card)
            if parsed:
                posts.append(parsed)
        return posts

    def _parse_card(self, card: Any) -> RawPost | None:
        title_el = card.select_one("a[class*='title'], a[href*='/internship/'], h3")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        job_url = title_el.get("href", "")
        if job_url and not job_url.startswith("http"):
            job_url = f"{BASE_URL}{job_url}"

        company_el = card.select_one("a[class*='company'], h4, [class*='company_name']")
        company_raw = company_el.get_text(strip=True) if company_el else ""
        company = re.sub(r'Actively hiring|Actively|Hiring', '', company_raw, flags=re.I).strip()

        loc_el = card.select_one("[class*='location'], [class*='place']")
        location = loc_el.get_text(strip=True) if loc_el else ""

        stipend_el = card.select_one("[class*='stipend'], [class*='salary']")
        stipend = stipend_el.get_text(strip=True) if stipend_el else ""

        link_match = re.search(r"/internship/detail/[^/]+-internship-(\d+)", job_url)
        ext_id = link_match.group(1) if link_match else str(hash(job_url))

        body = f"{title} at {company}. Location: {location}. Stipend: {stipend}"

        return RawPost(
            source=self.source,
            external_id=ext_id,
            url=job_url,
            title=title,
            body=body,
            author=company,
            score=1,
            raw_meta={"location": location, "stipend": stipend, "keyword": self.source},
        )
