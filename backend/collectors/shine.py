"""
collectors/shine.py — Shine.com job scraper with direct HTML parsing.

India's second-largest job portal: https://www.shine.com/
instead of raw httpx — no Playwright overhead required.

Env vars required: none (public HTML pages).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from backend.collectors.base import BaseCollector, RawPost

logger = structlog.get_logger(__name__)

SHINE_BASE_URL = "https://www.shine.com"


class ShineCollector(BaseCollector):

    source = "shine"

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        max_results: int = 50,
    ) -> None:
        self._keywords = keywords or self._default_keywords()
        self._locations = locations or self._default_locations()
        self._max_results = max_results

    async def collect(self) -> list[RawPost]:
        all_jobs: list[RawPost] = []
        for keyword in self._keywords:
            for location in self._locations:
                try:
                    jobs = await self._scrape_search(keyword, location)
                    all_jobs.extend(jobs)
                    logger.info("shine_search_complete", keyword=keyword, location=location, jobs_found=len(jobs))
                except Exception as e:
                    logger.warning("shine_search_failed", keyword=keyword, location=location, error=str(e))
        logger.info("ShineCollector fetched %d jobs", len(all_jobs))
        return all_jobs

    async def _scrape_search(self, keyword: str, location: str) -> list[RawPost]:
        url = self._search_url(keyword, location)
        result = await self._adapter.fetch(url)
        if not result.is_success():
            logger.warning("shine_fetch_failed", url=url, status=result.status, error=result.error)
            return []

        soup = BeautifulSoup(result.data.get("text", ""), "html.parser")
        cards = soup.select(
            "div.jobCard, div.job-card, div[class*=jobCard], "
            "div[class*=job_card], article[class*=job]"
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
                "a[class*=title], h2[class*=title], h3[class*=title], "
                ".job-title, [class*=jobTitle]"
            )
            title = title_el.get_text(strip=True) if title_el else ""
            href = title_el.get("href") if title_el and hasattr(title_el, "get") else ""
            link = f"{SHINE_BASE_URL}{href}" if href and href.startswith("/") else (href or "")

            company_el = card.select_one(
                "p[class*=company], span[class*=company], .company-name, "
                "[class*=compName], [class*=employer]"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            location_el = card.select_one(
                "span[class*=loc], p[class*=loc], .location, "
                "[class*=place], [class*=city]"
            )
            location = location_el.get_text(strip=True) if location_el else ""

            salary_el = card.select_one(
                "span[class*=salary], p[class*=salary], .salary, "
                "[class*=pay], [class*=sal]"
            )
            salary_text = salary_el.get_text(strip=True) if salary_el else ""
            salary_min, salary_max = self._parse_salary(salary_text)

            exp_el = card.select_one(
                "span[class*=exp], p[class*=exp], .experience, "
                "[class*=exp]"
            )
            exp_text = exp_el.get_text(strip=True) if exp_el else ""
            exp_min, exp_max = self._parse_experience(exp_text)

            skills: list[str] = []
            skills_el = card.select_one(
                "div[class*=skill], [class*=tag], [class*=keyword]"
            )
            if skills_el:
                skill_tags = skills_el.select("span, a, [class*=tag]")
                skills = [s.get_text(strip=True) for s in skill_tags if s.get_text(strip=True)]

            posted_el = card.select_one(
                "span[class*=posted], p[class*=posted], [class*=date], "
                "[class*=time]"
            )
            posted = posted_el.get_text(strip=True) if posted_el else ""

            job_type_el = card.select_one(
                "span[class*=type], [class*=work], [class*=mode]"
            )
            job_type = job_type_el.get_text(strip=True) if job_type_el else ""

            external_id = (
                str(card.get("data-job-id", ""))
                if hasattr(card, "get")
                else self._extract_id(link or href)
            )

            return RawPost(
                source=self.source,
                external_id=external_id or self._extract_id(link or href),
                url=link,
                title=title,
                body=(
                    f"Job at {company}. Location: {location}. "
                    f"Salary: {salary_text}. Experience: {exp_text}."
                )
                if title
                else "",
                author=company,
                score=0,
                raw_meta={
                    "company_name": company,
                    "location": location,
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "salary_text": salary_text,
                    "experience_min": exp_min,
                    "experience_max": exp_max,
                    "experience_text": exp_text,
                    "skills": skills,
                    "posted_date": posted,
                    "job_type": job_type,
                },
            )

        except Exception as exc:
            logger.warning("shine_card_parse_failed", error=str(exc))
            return None

    def _search_url(self, keyword: str, location: str) -> str:
        k = keyword.lower().replace(" ", "-")
        l = location.lower().replace(" ", "-")
        return f"{SHINE_BASE_URL}/search/job/{k}/{l}/"

    @staticmethod
    def _parse_salary(salary_str: str) -> tuple[int | None, int | None]:
        if not salary_str or salary_str.strip().lower() in (
            "not disclosed", "", "na", "negotiable"
        ):
            return None, None

        cleaned = salary_str.replace("₹", "").replace(",", "").strip().lower()

        is_monthly = "month" in cleaned or "/m" in cleaned
        has_k = bool(re.search(r"\d+\s*k", cleaned))

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

        cleaned = exp_str.strip().lower()
        if "fresher" in cleaned or "entry" in cleaned:
            return 0, 0

        numbers = [int(x) for x in re.findall(r"\d+", cleaned)]
        if len(numbers) >= 2:
            return numbers[0], numbers[1]
        if len(numbers) == 1:
            return numbers[0], numbers[0]
        return None, None

    @staticmethod
    def _extract_id(url_or_path: str) -> str:
        match = re.search(r"/job/([^/?]+)", url_or_path)
        if match:
            return match.group(1)

        match = re.search(r"job_id[=/](\d+)", url_or_path, re.IGNORECASE)
        if match:
            return match.group(1)

        return hashlib.md5(url_or_path.encode()).hexdigest()[:12]

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
            "kolkata",
            "ahmedabad",
        ]
