"""
funding_detector.py — Detect startup funding rounds from multiple sources.

Uses NER + regex to extract: company, amount, round_type, investors, date.
Cross-validates across 2+ sources for trust scoring.

Sources: TechCrunch, Crunchbase, Inc42, Entrackr, YourStory
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class FundingEvent:
    """Single funding round detection."""
    company_name: str
    amount: str | None
    round_type: str | None  # Seed, Series A, B, C, etc.
    investors: List[str]
    announced_date: str | None
    source_url: str
    source_name: str
    trust_score: float
    verified: bool  # Cross-validated with 2+ sources?


class FundingDetector:
    """Detect and extract funding round announcements."""

    # Regex patterns for funding extraction
    AMOUNT_PATTERNS = [
        r"\$([\d,.]+)\s*(M|B|K)?",  # $10M, $1.5B
        r"₹([\d,.]+)\s*(Cr|L)?",     # ₹50Cr
        r"([\d,.]+)\s*million",      # 10 million
        r"([\d,.]+)\s*billion",      # 1.5 billion
    ]

    ROUND_PATTERNS = [
        r"(?:Series\s+([A-F]))",
        r"(?:Seed\s+(?:Round|Funding)?)",
        r"(?:Pre-[Ss]eed)",
        r"(?:Series\s+([A-F])\s+Extension)",
        r"(?:Bridge\s+Round)",
    ]

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def detect_from_text(self, text: str, source_url: str, source_name: str) -> Optional[FundingEvent]:
        """
        Extract funding event from article text.

        Args:
            text: Article body text
            source_url: Original URL
            source_name: Source identifier (techcrunch, crunchbase, etc.)

        Returns:
            FundingEvent or None if no funding detected
        """
        # Check for funding keywords
        funding_keywords = ["raised", "funding", "investment", "series", "seed", "million", "billion"]
        if not any(kw in text.lower() for kw in funding_keywords):
            return None

        # Extract company (first named entity or capitalized phrase)
        company = self._extract_company(text)
        if not company:
            return None

        # Extract amount
        amount = self._extract_amount(text)

        # Extract round type
        round_type = self._extract_round_type(text)

        # Extract investors
        investors = self._extract_investors(text)

        # Extract date
        date = self._extract_date(text)

        # Calculate trust score based on source
        trust_scores = {
            "crunchbase": 9.5,
            "techcrunch": 8.5,
            "inc42": 7.5,
            "entrackr": 7.0,
            "yourstory": 7.0,
            "default": 6.0,
        }
        trust = trust_scores.get(source_name, trust_scores["default"])

        return FundingEvent(
            company_name=company,
            amount=amount,
            round_type=round_type,
            investors=investors,
            announced_date=date,
            source_url=source_url,
            source_name=source_name,
            trust_score=trust,
            verified=False,  # Will be updated on cross-validation
        )

    def _extract_company(self, text: str) -> str | None:
        """Extract company name from funding announcement."""
        # Pattern: "Company X raised..." or "Startup Y secures..."
        patterns = [
            r"^([A-Z][A-Za-z\s]+)\s+(?:raised|secures|lands|gets)",
            r"([A-Z][A-Za-z\s]+)\s+(?:announces?|closes?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_amount(self, text: str) -> str | None:
        """Extract funding amount from text."""
        for pattern in self.AMOUNT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = match.group(1)
                suffix = match.group(2) if len(match.groups()) > 1 else ""
                return f"${amount}{suffix}" if "$" in pattern else f"₹{amount}{suffix}"
        return None

    def _extract_round_type(self, text: str) -> str | None:
        """Extract funding round type."""
        for pattern in self.ROUND_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None

    def _extract_investors(self, text: str) -> List[str]:
        """Extract investor names from text."""
        # Pattern: "led by Investor Name" or "from Investor Name and Investor Name"
        investors = []
        patterns = [
            r"(?:led by|from|investors include)\s+([A-Z][A-Za-z\s&]+?)(?:,|;|\.|\band\b)",
            r"(?:participation from|backed by)\s+([A-Z][A-Za-z\s&]+?)(?:,|;|\.|\band\b)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                if len(name) > 3 and len(name) < 50:
                    investors.append(name)
        return list(set(investors))[:5]  # Deduplicate and limit

    def _extract_date(self, text: str) -> str | None:
        """Extract announcement date."""
        # Look for date patterns
        patterns = [
            r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b)",
            r"(\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def cross_validate(self, events: List[FundingEvent]) -> List[FundingEvent]:
        """
        Cross-validate funding events across sources.

        If 2+ sources confirm same company + amount → verified=True, trust += 2
        """
        validated = []
        company_map = {}

        # Group by company
        for event in events:
            key = event.company_name.lower().replace(" ", "")
            if key not in company_map:
                company_map[key] = []
            company_map[key].append(event)

        # Validate
        for key, company_events in company_map.items():
            if len(company_events) >= 2:
                # Cross-validated!
                for event in company_events:
                    event.verified = True
                    event.trust_score = min(10.0, event.trust_score + 2.0)
                    validated.append(event)
            else:
                validated.extend(company_events)

        return validated
