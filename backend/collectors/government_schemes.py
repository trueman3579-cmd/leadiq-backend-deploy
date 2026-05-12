"""
government_schemes.py — Scraper for Indian government startup schemes.

Sources:
    - startupindia.gov.in
    - msme.gov.in
    - sidbi.in
    - investindia.gov.in

All sources are official .gov.in domains with SSL — trust score 10/10.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class GovernmentScheme:
    """Single government scheme record."""
    name: str
    description: str
    eligibility: str
    deadline: str | None
    funding_amount: str | None
    source_url: str
    department: str
    trust_score: float = 10.0  # Government = highest trust


class GovernmentScraper:
    """Scrape Indian government startup schemes."""

    SOURCES = {
        "startupindia": {
            "url": "https://startupindia.gov.in/content/sih/en/government-schemes.html",
            "department": "DPIIT, Ministry of Commerce",
        },
        "msme": {
            "url": "https://www.msme.gov.in/schemes",
            "department": "Ministry of MSME",
        },
        "sidbi": {
            "url": "https://www.sidbi.in/schemes-for-startups",
            "department": "SIDBI",
        },
    }

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def scrape_all(self) -> List[GovernmentScheme]:
        """Scrape all government sources."""
        all_schemes = []
        for source_name, config in self.SOURCES.items():
            try:
                schemes = await self._scrape_source(source_name, config)
                all_schemes.extend(schemes)
                logger.info(f"Scraped {len(schemes)} schemes from {source_name}")
            except Exception as exc:
                logger.error(f"Failed to scrape {source_name}: {exc}")
        return all_schemes

    async def _scrape_source(
        self,
        source_name: str,
        config: dict,
    ) -> List[GovernmentScheme]:
        """Scrape a single government source."""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; LeadIQ-Scraper/1.0)",
            }
            async with session.get(config["url"], headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"HTTP {resp.status} from {source_name}")
                    return []

                html = await resp.text()
                return self._parse_html(html, config)

    def _parse_html(self, html: str, config: dict) -> List[GovernmentScheme]:
        """Parse HTML and extract schemes."""
        soup = BeautifulSoup(html, "html.parser")
        schemes = []

        # Generic extraction — specific selectors vary by site
        # In production, maintain per-site parsers
        for card in soup.find_all(["div", "article"], class_=lambda x: x and "scheme" in x.lower() if x else False):
            name = self._extract_text(card, "h2, h3, .scheme-title, .title")
            description = self._extract_text(card, ".description, .summary, p")
            eligibility = self._extract_text(card, ".eligibility, .criteria")
            deadline = self._extract_text(card, ".deadline, .last-date")
            funding = self._extract_text(card, ".funding, .amount, .grant")

            if name:  # Only add if we found at least a name
                schemes.append(GovernmentScheme(
                    name=name,
                    description=description or "",
                    eligibility=eligibility or "",
                    deadline=deadline,
                    funding_amount=funding,
                    source_url=config["url"],
                    department=config["department"],
                ))

        # Fallback: if no structured cards found, look for lists
        if not schemes:
            for li in soup.find_all("li"):
                text = li.get_text(strip=True)
                if len(text) > 20 and any(kw in text.lower() for kw in ["scheme", "grant", "fund", "subsidy"]):
                    schemes.append(GovernmentScheme(
                        name=text[:100],
                        description=text,
                        eligibility="",
                        deadline=None,
                        funding_amount=None,
                        source_url=config["url"],
                        department=config["department"],
                    ))

        return schemes

    def _extract_text(self, element, selector: str) -> str | None:
        """Extract text from first matching child."""
        child = element.select_one(selector)
        return child.get_text(strip=True) if child else None

    def to_dict_list(self, schemes: List[GovernmentScheme]) -> List[dict]:
        """Convert to dict for API response."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "eligibility": s.eligibility,
                "deadline": s.deadline,
                "funding_amount": s.funding_amount,
                "source_url": s.source_url,
                "department": s.department,
                "trust_score": s.trust_score,
            }
            for s in schemes
        ]
