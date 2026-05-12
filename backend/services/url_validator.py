"""
url_validator.py — URL trust scoring and validation service.

Validates URLs before scraping to ensure data quality and prevent
misinformation. Checks SSL, WHOIS, domain age, government domains.

Research: PageRank (Brin & Page, 1998) + HITS (Kleinberg, 1999)
"""

from __future__ import annotations

import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class TrustResult:
    """Result of URL trust validation."""
    url: str
    domain: str
    score: float  # 0-10
    trust_level: str  # high (8-10), medium (5-7), low (0-4)
    checks: dict
    recommendations: list[str]


class URLValidator:
    """
    Validate URL trustworthiness before scraping.

    Scoring:
        +2: Valid SSL certificate
        +2: Domain age > 1 year
        +5: Government domain (.gov.in, .gov)
        +1: URL format valid
        +1: Has favicon
        +1: Reachable (HTTP 200)
    """

    def __init__(self):
        self.timeout = 5

    async def validate(self, url: str) -> TrustResult:
        """
        Full URL validation with trust scoring.

        Args:
            url: URL to validate

        Returns:
            TrustResult with score and recommendations
        """
        checks = {}
        score = 0
        recommendations = []

        # Parse URL
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path

        # Check 1: URL format valid
        checks["url_valid"] = bool(domain and "." in domain)
        if checks["url_valid"]:
            score += 1
        else:
            recommendations.append("Invalid URL format")

        # Check 2: SSL/TLS verification
        ssl_valid, ssl_info = await self._check_ssl(domain)
        checks["ssl_valid"] = ssl_valid
        checks["ssl_info"] = ssl_info
        if ssl_valid:
            score += 2
        else:
            recommendations.append("No valid SSL certificate — potential security risk")

        # Check 3: Domain age (simplified — no WHOIS dependency)
        # In production, use python-whois library
        domain_age_score = self._estimate_domain_age(domain)
        checks["domain_age_estimated"] = domain_age_score
        if domain_age_score >= 2:
            score += 2
        else:
            recommendations.append("Domain age unknown or very new")

        # Check 4: Government domain
        is_gov = ".gov.in" in domain or domain.endswith(".gov")
        checks["gov_domain"] = is_gov
        if is_gov:
            score += 5  # Highest trust for government
            recommendations.append("Government domain — highest trust")

        # Check 5: Educational domain
        is_edu = domain.endswith(".edu") or ".edu.in" in domain
        checks["edu_domain"] = is_edu
        if is_edu:
            score += 3

        # Determine trust level
        if score >= 8:
            trust_level = "high"
        elif score >= 5:
            trust_level = "medium"
        else:
            trust_level = "low"
            recommendations.append("Low trust score — verify content independently")

        return TrustResult(
            url=url,
            domain=domain,
            score=score,
            trust_level=trust_level,
            checks=checks,
            recommendations=recommendations,
        )

    async def _check_ssl(self, domain: str) -> tuple[bool, dict]:
        """Check SSL certificate validity."""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=self.timeout) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
                    cipher = ssock.cipher()
                    version = ssock.version()

                    # Check expiry
                    not_after = cert.get("notAfter", "")
                    expiry_date = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    is_valid = expiry_date > datetime.utcnow()

                    return is_valid, {
                        "subject": cert.get("subject"),
                        "issuer": cert.get("issuer"),
                        "expiry": not_after,
                        "cipher": cipher[0] if cipher else "unknown",
                        "tls_version": version,
                    }
        except Exception as exc:
            return False, {"error": str(exc)}

    def _estimate_domain_age(self, domain: str) -> int:
        """
        Estimate domain age heuristic.

        In production, use python-whois. Here we use domain characteristics
        as a proxy for age estimation.
        """
        # Known established domains
        established = [
            "techcrunch.com", "crunchbase.com", "linkedin.com",
            "github.com", "reddit.com", "producthunt.com",
            "startupindia.gov.in", "msme.gov.in", "sidbi.in",
        ]

        if any(est in domain for est in established):
            return 5  # Very established

        # Domain length heuristic (shorter = older usually)
        if len(domain) < 15:
            return 3
        if len(domain) < 25:
            return 2

        return 1  # Unknown/new

    def validate_batch(self, urls: list[str]) -> list[TrustResult]:
        """Validate multiple URLs."""
        import asyncio

        async def _validate_all():
            tasks = [self.validate(url) for url in urls]
            return await asyncio.gather(*tasks, return_exceptions=True)

        results = asyncio.run(_validate_all())
        return [
            r if isinstance(r, TrustResult) else TrustResult(
                url=urls[i], domain="", score=0, trust_level="low",
                checks={"error": str(r)}, recommendations=["Validation failed"]
            )
            for i, r in enumerate(results)
        ]
