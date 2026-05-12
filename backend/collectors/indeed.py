"""
collectors/indeed.py — Indeed India job listing collector (refactored).

with liveness checking and reliability telemetry via the new services.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost
from backend.services.source_pattern_learner import SourcePatternLearner

logger = structlog.get_logger(__name__)

INDEED_BASE_URL = "https://in.indeed.com"
INDEED_JOBS_SEARCH = f"{INDEED_BASE_URL}/jobs"


class IndeedCollector(BaseCollector):
    source = "indeed"

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_results_per_search: int = 50,
    ) -> None:
        self._keywords = keywords or self._default_keywords()
        self._locations = locations or self._default_locations()
        self._max_per_search = max_results_per_search
        self._pattern_learner = SourcePatternLearner()
        self._intercepted_data: list[dict[str, Any]] = []

    async def collect(self) -> list[RawPost]:
        all_jobs: list[RawPost] = []
        for keyword in self._keywords:
            for location in self._locations:
                try:
                    jobs = await self._scrape_search(keyword, location)
                    all_jobs.extend(jobs)
                    logger.info("indeed_search_complete", keyword=keyword, location=location, jobs_found=len(jobs))
                except Exception as exc:
                    logger.warning("indeed_search_failed", keyword=keyword, location=location, error=str(exc))
                await self._random_delay()
        logger.info("IndeedCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape_search(self, keyword: str, location: str) -> list[RawPost]:
        search_url = (
            f"{INDEED_JOBS_SEARCH}?"
            f"q={keyword.replace(' ', '+')}"
            f"&l={location.replace(' ', '+')}"
            f"&sort=date"
        )

        mode = self._pattern_learner.suggest_fetch_mode(search_url)
        result = await self._adapter.fetch(search_url, mode=mode)
        self._pattern_learner.record_result(
            search_url, result.status, result.response_time_ms
        )

        if not result.is_success():
            logger.warning("indeed_fetch_failed", url=search_url, status=result.status, error=result.error)
            return []

        jobs = self._parse_html(result.data.get("text", ""))
        raw_posts = []
        for job in jobs[: self._max_per_search]:
            rp = self._transform(job)
            raw_posts.append(rp)

        return raw_posts

    def _parse_html(self, html: str | bytes) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, Any]] = []
        seen_jks: set[str] = set()

        cards = soup.select(
            "div[class*='cardOutline'], div.job_seen_beacon, "
            "li[class*='job'], div[class*='jobsearch'] div[class*='result']"
        )
        embedded = self._extract_embedded_json(soup)

        for card in cards:
            job = self._parse_card(card)
            jk = str(job.get("jobId", ""))
            if jk and jk in seen_jks:
                continue
            if jk:
                seen_jks.add(jk)
            if job.get("title"):
                jobs.append(job)

        if embedded:
            emap = {e.get("jobId", ""): e for e in embedded if e.get("jobId")}
            for job in jobs:
                jk = job.get("jobId", "")
                if jk in emap:
                    for field in ("salary", "description", "jobType"):
                        if not job.get(field) and emap[jk].get(field):
                            job[field] = emap[jk][field]
        return jobs

    def _parse_card(self, card: Any) -> dict[str, Any]:
        job_id = (
            card.get("data-jk")
            or card.get("id", "").replace("job_", "").replace("sj_", "")
        )
        if not job_id:
            link = card.select_one("a[href*='jk=']")
            if link:
                href = link.get("href", "")
                m = re.search(r"jk=([^&]+)", href)
                if m:
                    job_id = m.group(1)

        title = self._safe_extract(
            card,
            "h2[class*='jobTitle'], span[title], a[class*='jobTitle'], "
            "h2[class*='title'], span[class*='jobTitle'], "
            "a[id*='job-title'], h2"
        )
        if not title:
            span = card.select_one("span[title]")
            if span:
                title = span.get("title", "") or span.get_text(strip=True)

        company = self._safe_extract(
            card,
            "span[class*='company'], [data-testid='company-name'], "
            "span[data-testid='company-name'], a[class*='company']"
        )
        if not company:
            el = card.select_one("div[class*='company'] span")
            if el:
                company = el.get_text(strip=True)

        location = self._safe_extract(card, "[data-testid='location'], div[class*='location'], span[class*='location']")
        salary = self._safe_extract(card, "[data-testid='salary'], span[class*='salary'], div[class*='salary']")
        description = self._safe_extract(card, "div[class*='snippet'], div.job-snippet")
        posted_date = self._safe_extract(card, "[data-testid='date'], span[class*='date'], div[class*='posted']")

        return {
            "jobId": job_id,
            "title": title,
            "companyName": company,
            "location": location,
            "salary": salary,
            "description": description,
            "postedDate": posted_date,
        }

    @staticmethod
    def _extract_embedded_json(soup: BeautifulSoup) -> list[dict[str, Any]]:
        jobs = []
        for script in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        jobs.append({
                            "jobId": item.get("identifier", ""),
                            "title": item.get("title", ""),
                            "companyName": (
                                item.get("hiringOrganization", {}).get("name", "")
                                if isinstance(item.get("hiringOrganization"), dict) else ""
                            ),
                            "location": (
                                item.get("jobLocation", {}).get("address", {}).get("addressLocality", "")
                                if isinstance(item.get("jobLocation"), dict) else ""
                            ),
                            "salary": (
                                item.get("baseSalary", {}).get("value", {}).get("value", "")
                                if isinstance(item.get("baseSalary"), dict) else ""
                            ),
                            "description": (
                                BeautifulSoup(item.get("description", ""), "html.parser").get_text(strip=True)
                            ),
                            "postedDate": item.get("datePosted", ""),
                            "jobType": item.get("employmentType", ""),
                        })
            except (json.JSONDecodeError, TypeError):
                continue
        return jobs

    def _transform(self, job: dict[str, Any]) -> RawPost:
        salary_min, salary_max = self._parse_salary(job.get("salary") or "")
        job_id = str(job.get("jobId", ""))
        company = str(job.get("companyName", ""))
        return RawPost(
            source=self.source,
            external_id=job_id,
            url=f"{INDEED_BASE_URL}/viewjob?jk={job_id}" if job_id else "",
            title=str(job.get("title", "")),
            body=str(job.get("description", "")),
            author=company,
            score=float(job.get("companyRating") or 0),
            raw_meta={
                "company_name": company,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "location": str(job.get("location", "")),
                "posted_date": str(job.get("postedDate", "")),
                "job_type": str(job.get("jobType", "")),
                "company_rating": job.get("companyRating"),
                "company_reviews": job.get("companyReviews", 0),
                "platform": "indeed",
            },
        )

    @staticmethod
    def _parse_salary(salary_str: str) -> tuple[int | None, int | None]:
        if not salary_str or salary_str.strip().lower() in ("not specified", "not disclosed", "", "na"):
            return None, None
        cleaned = salary_str.replace("₹", "").replace(",", "").strip()
        is_monthly = "month" in cleaned.lower()
        has_l = bool(re.search(r"\d+\s*L", cleaned, re.I))
        numbers = [int(x) for x in re.findall(r"\d+", cleaned)]
        if len(numbers) >= 2:
            lo, hi = numbers[0], numbers[1]
        elif len(numbers) == 1:
            lo = hi = numbers[0]
        else:
            return None, None
        if has_l and hi < 1000:
            lo, hi = lo * 100_000, hi * 100_000
        if is_monthly:
            lo, hi = lo * 12, hi * 12
        return lo, hi

    @staticmethod
    def _safe_extract(soup: Any, selector: str) -> str:
        elem = soup.select_one(selector)
        return elem.get_text(strip=True) if elem else ""

    @staticmethod
    def _default_keywords() -> list[str]:
        return [
            "software engineer", "data scientist", "product manager",
            "devops engineer", "frontend developer", "backend developer",
            "full stack developer", "machine learning engineer",
            "cloud architect", "cybersecurity analyst",
        ]

    @staticmethod
    def _default_locations() -> list[str]:
        return ["Bangalore", "Hyderabad", "Pune", "Mumbai", "Chennai", "Delhi NCR", "Gurgaon", "Noida"]

    @staticmethod
    async def _random_delay() -> None:
        import random
        await asyncio.sleep(random.uniform(2.0, 5.0))
