"""
collectors/linkedin_jobs.py — LinkedIn Jobs collector (refactored).

then parses the rendered HTML with BeautifulSoup.

LinkedIn public job listings: https://www.linkedin.com/jobs/search/
No API interception since LinkedIn's GraphQL API requires authenticated session cookies.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

LINKEDIN_BASE_URL = "https://www.linkedin.com"
LINKEDIN_JOBS_SEARCH = f"{LINKEDIN_BASE_URL}/jobs/search"


class LinkedInJobsCollector(BaseCollector):

    source = "linkedin_jobs"

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_results_per_search: int = 25,
    ) -> None:
        self._keywords = keywords or self._default_keywords()
        self._locations = locations or self._default_locations()
        self._max_per_search = max_results_per_search

    async def collect(self) -> list[RawPost]:
        all_jobs: list[RawPost] = []

        for keyword in self._keywords:
            for location in self._locations:
                try:
                    jobs = await self._scrape_search(keyword, location)
                    all_jobs.extend(jobs)
                    logger.info(
                        "linkedin_jobs_search_complete",
                        keyword=keyword,
                        location=location,
                        jobs_found=len(jobs),
                    )
                except Exception as exc:
                    logger.warning(
                        "linkedin_jobs_search_failed",
                        keyword=keyword,
                        location=location,
                        error=str(exc),
                    )
                await self._random_delay()

        logger.info("LinkedInJobsCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape_search(self, keyword: str, location: str) -> list[RawPost]:
        search_url = (
            f"{LINKEDIN_JOBS_SEARCH}/?"
            f"keywords={keyword.replace(' ', '%20')}"
            f"&location={location.replace(' ', '%20')}"
            f"&trk=public_jobs_jobs-search-bar_search-submit"
            f"&position=1&pageNum=0"
        )

        result = await self._adapter.fetch(search_url, mode=FetchMode.STEALTH)

        if not result.is_success():
            logger.warning(
                "linkedin_jobs_fetch_failed",
                url=search_url,
                status=result.status,
                error=result.error,
            )
            return []

        jobs = self._parse_html(result.data.get("text", ""))
        return [self.transform(j) for j in jobs[: self._max_per_search]]

    def _parse_html(self, html: str | bytes) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")

        jobs: list[dict[str, Any]] = []

        cards = soup.select(
            "li[data-occludable-job-id], "
            "div.job-card-container, "
            "div[data-job-id], "
            "article.job-card"
        )

        seen_ids: set[str] = set()

        for card in cards:
            job_id = (
                card.get("data-occludable-job-id")
                or card.get("data-job-id")
                or ""
            )
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)

            job_data = self._parse_card(card, job_id)
            if job_data["title"]:
                jobs.append(job_data)

        return jobs

    def _parse_card(self, card: Any, job_id: str) -> dict[str, Any]:
        title = self._safe_extract(
            card,
            "a.job-card-list__title, "
            "a.job-card-container__link, "
            "a[class*='job-title'], "
            "a[class*='jobCard'] h3, "
            "h3[class*='job'], "
            "span[class*='job-title'], "
            "span[class*='jobTitle']",
        )

        company = self._safe_extract(
            card,
            "a.job-card-container__company-name, "
            "span.job-card-container__company-name, "
            "span[class*='company-name'], "
            "span[class*='companyName'], "
            "div[class*='company'] span",
        )

        if not company:
            img = card.select_one("img[alt]")
            if img:
                company = img.get("alt", "")

        location = self._safe_extract(
            card,
            "span.job-card-container__metadata-item, "
            "li.job-card-container__metadata-item, "
            "span[class*='location'], "
            "div[class*='location']",
        )

        salary = self._safe_extract(
            card,
            "span[class*='salary'], "
            "span[class*='pay'], "
            "div[class*='salary'], "
            "div[class*='compensation']",
        )

        description = self._safe_extract(
            card,
            "div[class*='description'], "
            "div[class*='job-details'], "
            "p[class*='description']",
        )

        posted_date = self._safe_extract(
            card,
            "time, "
            "span[class*='posted'], "
            "span[class*='date'], "
            "div[class*='posted']",
        )

        time_el = card.select_one("time")
        if time_el and time_el.has_attr("datetime"):
            posted_date = str(time_el["datetime"])

        return {
            "jobId": job_id,
            "title": title,
            "companyName": company,
            "location": location,
            "salary": salary,
            "description": description,
            "postedDate": posted_date,
        }

    def transform(self, job: dict[str, Any]) -> RawPost:
        salary_min, salary_max = self._parse_salary(job.get("salary") or "")
        job_id = str(job.get("jobId", ""))
        company = str(job.get("companyName", ""))

        return RawPost(
            source=self.source,
            external_id=job_id,
            url=(
                f"{LINKEDIN_BASE_URL}/jobs/view/{job_id}"
                if job_id
                else ""
            ),
            title=str(job.get("title", "")),
            body=str(job.get("description", "")),
            author=company,
            score=0,
            raw_meta={
                "company_name": company,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "location": str(job.get("location", "")),
                "posted_date": str(job.get("postedDate", "")),
                "platform": "linkedin",
            },
        )

    @staticmethod
    def _parse_salary(salary_str: str) -> tuple[int | None, int | None]:
        if not salary_str or salary_str.strip().lower() in (
            "not specified", "not disclosed", "", "na"
        ):
            return None, None

        cleaned = salary_str.replace("$", "").replace(",", "").strip()
        has_k = bool(re.search(r"\d+\s*K", cleaned, re.IGNORECASE))
        numbers = [int(x) for x in re.findall(r"\d+", cleaned)]

        if len(numbers) >= 2:
            lo, hi = numbers[0], numbers[1]
        elif len(numbers) == 1:
            lo = hi = numbers[0]
        else:
            return None, None

        if has_k:
            lo, hi = lo * 1_000, hi * 1_000

        return lo, hi

    @staticmethod
    def _safe_extract(soup: Any, selector: str) -> str:
        elem = soup.select_one(selector)
        return elem.get_text(strip=True) if elem else ""

    @staticmethod
    def _default_keywords() -> list[str]:
        return [
            "software engineer",
            "data scientist",
            "product manager",
            "devops engineer",
            "frontend developer",
            "backend developer",
            "full stack developer",
            "machine learning engineer",
            "cloud architect",
            "site reliability engineer",
        ]

    @staticmethod
    def _default_locations() -> list[str]:
        return [
            "Bangalore",
            "Hyderabad",
            "Pune",
            "Mumbai",
            "Chennai",
            "Delhi NCR",
            "Gurgaon",
            "Noida",
        ]

    @staticmethod
    async def _random_delay() -> None:
        import random as _random
        await asyncio.sleep(_random.uniform(3.0, 7.0))


if __name__ == "__main__":
    import logging

    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        collector = LinkedInJobsCollector()
        results = await collector.collect()
        print(f"Collected {len(results)} jobs")
        for r in results[:5]:
            print(f"  {r.title} @ {r.author} [{r.raw_meta.get('location')}]")

    asyncio.run(_main())
