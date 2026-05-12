"""
collectors/naukri.py — Naukri.com job scraper (refactored).

then parses the rendered HTML with BeautifulSoup.

India's largest job portal: https://www.naukri.com/
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

NAUKRI_BASE_URL = "https://www.naukri.com"


class NaukriCollector(BaseCollector):

    source = "naukri"

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_results_per_search: int = 50,
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
                        "naukri_search_complete",
                        keyword=keyword,
                        location=location,
                        jobs_found=len(jobs),
                    )
                except Exception as exc:
                    logger.warning(
                        "naukri_search_failed",
                        keyword=keyword,
                        location=location,
                        error=str(exc),
                    )
                await self._random_delay()

        logger.info("NaukriCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape_search(self, keyword: str, location: str) -> list[RawPost]:
        search_path = f"{keyword.replace(' ', '-')}-jobs-in-{location}"
        search_url = f"{NAUKRI_BASE_URL}/{search_path}"

        result = await self._adapter.fetch(search_url, mode=FetchMode.STEALTH)

        if not result.is_success():
            logger.warning(
                "naukri_fetch_failed",
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
        for card in soup.select("article.jobTuple, div.jobTuple, div[class*=job]"):
            jobs.append(
                {
                    "jobId": self._safe_extract(card, "[data-job-id]"),
                    "title": self._safe_extract(
                        card, "a.title, .title, [class*=title]"
                    ),
                    "companyName": self._safe_extract(
                        card, "a.company-name, .company-name, [class*=company]"
                    ),
                    "location": self._safe_extract(
                        card, ".location, [class*=loc]"
                    ),
                    "experience": self._safe_extract(
                        card, ".experience, [class*=exp]"
                    ),
                    "salary": self._safe_extract(
                        card, ".salary, [class*=salary], [class*=sal]"
                    ),
                    "description": self._safe_extract(
                        card, ".job-description, [class*=desc]"
                    ),
                    "skills": [],
                    "workMode": "",
                    "jobType": "",
                    "postedDate": "",
                    "applyCount": 0,
                    "ambitionBoxRating": None,
                }
            )

        return jobs

    def transform(self, job: dict[str, Any]) -> RawPost:
        salary_min, salary_max = self._parse_salary(job.get("salary") or "")
        exp_min, exp_max = self._parse_experience(job.get("experience") or "")
        job_id = str(job.get("jobId", ""))
        company = str(job.get("companyName", ""))

        return RawPost(
            source=self.source,
            external_id=job_id,
            url=f"{NAUKRI_BASE_URL}/job-listings-{job_id}" if job_id else "",
            title=str(job.get("title", "")),
            body=str(job.get("description", "")),
            author=company,
            score=int(job.get("ambitionBoxRating") or 0),
            raw_meta={
                "company_name": company,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "experience_min": exp_min,
                "experience_max": exp_max,
                "location": str(job.get("location", "")),
                "skills": job.get("skills", []),
                "work_mode": str(job.get("workMode", "")),
                "job_type": str(job.get("jobType", "")),
                "posted_date": str(job.get("postedDate", "")),
                "apply_count": job.get("applyCount", 0),
                "ambition_box_rating": job.get("ambitionBoxRating"),
            },
        )

    @staticmethod
    def _parse_salary(salary_str: str) -> tuple[int | None, int | None]:
        if not salary_str or salary_str.strip().lower() in (
            "not disclosed",
            "",
            "na",
        ):
            return None, None

        cleaned = salary_str.replace("₹", "").replace(",", "").strip()
        is_monthly = "month" in cleaned.lower() or "/m" in cleaned.lower()
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

        if is_monthly:
            lo, hi = lo * 12, hi * 12
        else:
            if not has_k and hi < 1000:
                lo, hi = lo * 100_000, hi * 100_000

        return lo, hi

    @staticmethod
    def _parse_experience(exp_str: str) -> tuple[int | None, int | None]:
        if not exp_str or not exp_str.strip():
            return None, None
        numbers = [int(x) for x in re.findall(r"\d+", exp_str)]
        if len(numbers) >= 2:
            return numbers[0], numbers[1]
        if len(numbers) == 1:
            return numbers[0], numbers[0]
        return None, None

    @staticmethod
    def _safe_extract(soup: Any, selector: str) -> str:
        elem = soup.select_one(selector)
        return elem.get_text(strip=True) if elem else ""

    @staticmethod
    def _default_keywords() -> list[str]:
        return [
            "software-engineer",
            "data-scientist",
            "product-manager",
            "devops-engineer",
            "frontend-developer",
            "backend-developer",
            "full-stack-developer",
            "machine-learning-engineer",
            "cloud-architect",
            "cybersecurity-analyst",
        ]

    @staticmethod
    def _default_locations() -> list[str]:
        return [
            "bangalore",
            "hyderabad",
            "pune",
            "chennai",
            "mumbai",
            "delhi",
            "gurgaon",
            "noida",
        ]

    @staticmethod
    async def _random_delay() -> None:
        import random as _random
        await asyncio.sleep(_random.uniform(2.0, 5.0))


if __name__ == "__main__":
    import logging

    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        collector = NaukriCollector()
        results = await collector.collect()
        print(f"Collected {len(results)} jobs")
        for r in results[:5]:
            print(f"  {r.title} @ {r.author} [{r.raw_meta.get('location')}]")

    asyncio.run(_main())
