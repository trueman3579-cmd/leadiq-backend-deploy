"""
job_signals.py — Detect hiring signals as demand indicators.

Scrapes "Who's Hiring" threads and job boards to track hiring velocity.
Rapid hiring = high intent score (company is growing = likely buying).

Sources: Hacker News Who's Hiring, Reddit r/forhire, LinkedIn, Indeed
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class JobSignal:
    """Single job posting signal."""
    company_name: str
    role: str
    skills: List[str]
    location: str | None
    salary_range: str | None
    source_url: str
    source_name: str
    posted_at: str | None
    hiring_velocity: int  # 1-10, calculated from frequency
    trust_score: float


class JobSignalDetector:
    """Detect and extract job postings as buying signals."""

    SOURCES = {
        "hn_whoshiring": {
            "url": "https://news.ycombinator.com/submitted?id=whoishiring",
            "name": "Hacker News",
        },
        "reddit_forhire": {
            "url": "https://www.reddit.com/r/forhire/search/?q=hiring&restrict_sr=1&sort=new",
            "name": "Reddit",
        },
    }

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def detect_signals(self, source: str | None = None) -> List[JobSignal]:
        """Detect job signals from all or specific source."""
        sources = [source] if source else list(self.SOURCES.keys())
        all_signals = []

        for src in sources:
            config = self.SOURCES.get(src)
            if not config:
                continue
            try:
                signals = await self._scrape_source(src, config)
                all_signals.extend(signals)
            except Exception as exc:
                logger.error(f"Job signal scrape failed for {src}: {exc}")

        return all_signals

    async def _scrape_source(self, source_name: str, config: dict) -> List[JobSignal]:
        """Scrape a job source."""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadIQ-Scraper/1.0)"}
            async with session.get(config["url"], headers=headers) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
                return self._parse_jobs(html, config["url"], config["name"])

    def _parse_jobs(self, html: str, source_url: str, source_name: str) -> List[JobSignal]:
        """Parse job postings from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        signals = []

        # HN specific parsing
        if "hackernews" in source_url or "ycombinator" in source_url:
            for row in soup.find_all("tr", class_="athing"):
                title_elem = row.find("span", class_="titleline")
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if any(kw in title.lower() for kw in ["hiring", "remote", "engineer", "developer"]):
                        company, role = self._extract_company_role(title)
                        if company:
                            signals.append(JobSignal(
                                company_name=company,
                                role=role or "",
                                skills=self._extract_skills(title),
                                location="Remote" if "remote" in title.lower() else None,
                                salary_range=self._extract_salary(title),
                                source_url=source_url,
                                source_name=source_name,
                                posted_at=None,
                                hiring_velocity=8 if "hiring" in title.lower() else 5,
                                trust_score=8.5,
                            ))

        return signals

    def _extract_company_role(self, text: str) -> tuple[str | None, str | None]:
        """Extract company and role from job title."""
        # Pattern: "Company is hiring Role" or "Company: Role"
        patterns = [
            r"^([A-Z][A-Za-z0-9\s]+)\s+(?:is\s+hiring|hiring|seeks?)\s+(.+)",
            r"^([A-Z][A-Za-z0-9\s]+):\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip(), match.group(2).strip()
        return None, None

    def _extract_skills(self, text: str) -> List[str]:
        """Extract tech skills from job text."""
        common_skills = [
            "python", "javascript", "typescript", "react", "node", "go", "rust",
            "sql", "aws", "gcp", "azure", "docker", "kubernetes", "ml", "ai",
            "backend", "frontend", "fullstack", "devops", "data", "product",
        ]
        found = []
        text_lower = text.lower()
        for skill in common_skills:
            if skill in text_lower:
                found.append(skill)
        return found[:5]

    def _extract_salary(self, text: str) -> str | None:
        """Extract salary range if mentioned."""
        patterns = [
            r"\$([\d,.]+k?-[\d,.]+k?)",
            r"₹([\d,.]+\s*L-[\d,.]+\s*L)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None
