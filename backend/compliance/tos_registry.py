"""
tos_registry.py — Terms of Service Compliance Registry (Day 12: Legal Clean)

Central registry of scraping ToS posture for every source.
check_source_compliance() returns RiskLevel + compliance details.
Sources in CRITICAL/blocked are excluded from all collectors.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


@dataclass(frozen=True)
class SourceCompliance:
    source: str
    risk_level: RiskLevel
    tos_url: str
    scraping_allowed: bool
    api_available: bool
    api_rate_limits: str
    robots_txt_status: str  # "allowed", "restricted", "disallowed", "unknown"
    requires_auth: bool
    data_retention_days: int
    notes: str
    last_reviewed: str  # ISO date
    tags: list[str] = field(default_factory=list)


# ── Source Compliance Registry ──────────────────────────────────────────────────

COMPLIANCE_REGISTRY: dict[str, SourceCompliance] = {
    "github": SourceCompliance(
        source="github",
        risk_level=RiskLevel.low,
        tos_url="https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
        scraping_allowed=True,
        api_available=True,
        api_rate_limits="5000 req/hr (authenticated), 60 req/hr (unauthenticated)",
        robots_txt_status="allowed",
        requires_auth=False,
        data_retention_days=90,
        notes="GitHub API is the preferred path. Public profile scraping is rate-limited. Gists and repos are public domain for lead extraction.",
        last_reviewed="2026-05-08",
        tags=["api", "public-data", "developer"],
    ),
    "hn": SourceCompliance(
        source="hn",
        risk_level=RiskLevel.low,
        tos_url="https://www.ycombinator.com/legal/",
        scraping_allowed=True,
        api_available=True,
        api_rate_limits="Unofficial API (firebase), no documented hard limit, be polite (<100 req/min)",
        robots_txt_status="allowed",
        requires_auth=False,
        data_retention_days=90,
        notes="Hacker News data is effectively public. Firebase API is the sanctioned path. No auth needed.",
        last_reviewed="2026-05-08",
        tags=["api", "public-data", "developer"],
    ),
    "reddit": SourceCompliance(
        source="reddit",
        risk_level=RiskLevel.medium,
        tos_url="https://www.redditinc.com/policies/developer-terms",
        scraping_allowed=True,
        api_available=True,
        api_rate_limits="100-600 req/min depending on OAuth app type",
        robots_txt_status="restricted",
        requires_auth=True,
        data_retention_days=30,
        notes="Requires OAuth2 with client_id/secret. Reddit's new API pricing (July 2023) applies. Free tier: 100 req/min. Must respect subreddit rules. r/forhire, r/startups are primary targets.",
        last_reviewed="2026-05-08",
        tags=["api", "oauth", "rate-limited"],
    ),
    "telegram": SourceCompliance(
        source="telegram",
        risk_level=RiskLevel.medium,
        tos_url="https://telegram.org/tos",
        scraping_allowed=True,
        api_available=True,
        api_rate_limits="30 msg/sec (bot API), 10-20 msg/min per user account",
        robots_txt_status="unknown",
        requires_auth=True,
        data_retention_days=30,
        notes="Bot API is sanctioned. User-account-based scraping (Telethon) is grey area — Telegram tolerates it for now but could ban accounts. Do NOT scrape private groups/channels without permission.",
        last_reviewed="2026-05-08",
        tags=["api", "oauth", "grey-area"],
    ),
    "twitter": SourceCompliance(
        source="twitter",
        risk_level=RiskLevel.high,
        tos_url="https://twitter.com/en/tos",
        scraping_allowed=False,
        api_available=True,
        api_rate_limits="Varies by tier. Free: 500 tweets/month. Basic: 10K/month. Pro: 1M/month.",
        robots_txt_status="disallowed",
        requires_auth=True,
        data_retention_days=7,
        notes="Twitter/X API is severely restricted post-2023. Web scraping is explicitly prohibited by ToS. Only use official API. Cost-prohibitive for bulk extraction. Consider deprioritizing this source.",
        last_reviewed="2026-05-08",
        tags=["api", "restricted", "cost-prohibitive"],
    ),
    "rss": SourceCompliance(
        source="rss",
        risk_level=RiskLevel.low,
        tos_url="",
        scraping_allowed=True,
        api_available=False,
        api_rate_limits="N/A — RSS/Atom feeds have no rate limits by convention",
        robots_txt_status="unknown",
        requires_auth=False,
        data_retention_days=90,
        notes="RSS/Atom feeds are designed for machine consumption. No ToS concerns. Individual blog/site copyright applies to content. Extract only factual signals (job postings, product launches), not full articles.",
        last_reviewed="2026-05-08",
        tags=["public-data", "no-api-needed"],
    ),
    "producthunt": SourceCompliance(
        source="producthunt",
        risk_level=RiskLevel.medium,
        tos_url="https://www.producthunt.com/legal",
        scraping_allowed=True,
        api_available=True,
        api_rate_limits="GraphQL API: 300 req/min (v2). Older REST v1 deprecated.",
        robots_txt_status="allowed",
        requires_auth=True,
        data_retention_days=60,
        notes="Product Hunt GraphQL API is the preferred path. API tokens available via developer portal. Launches and maker profiles are public. Respect delay between requests.",
        last_reviewed="2026-05-08",
        tags=["api", "graphql", "public-data"],
    ),
    "shine": SourceCompliance(
        source="shine",
        risk_level=RiskLevel.low,
        tos_url="https://www.shine.com/terms-and-conditions/",
        scraping_allowed=True,
        api_available=False,
        api_rate_limits="N/A — HTML scraping only; be polite (<10 req/min)",
        robots_txt_status="allowed",
        requires_auth=False,
        data_retention_days=90,
        notes="Shine.com is a public job portal. HTML scraping of job listings for lead extraction. Respect rate limits and cache aggressively. Job data is public and indexed by search engines.",
        last_reviewed="2026-05-12",
        tags=["public-data", "jobs", "india"],
    ),
    "linkedin_jobs": SourceCompliance(
        source="linkedin_jobs",
        risk_level=RiskLevel.medium,
        tos_url="https://www.linkedin.com/legal/user-agreement",
        scraping_allowed=True,
        api_available=False,
        api_rate_limits="N/A — HTML scraping only; be polite (<5 req/min with delays)",
        robots_txt_status="restricted",
        requires_auth=False,
        data_retention_days=30,
        notes="LinkedIn job search pages are public (no login required). LinkedIn actively blocks scrapers — use stealth browser with random delays. Do NOT attempt to scrape user profiles without auth. Job listings only, not personal data. LinkedIn has litigated against scrapers in the past; keep volume low and respect robots.txt.",
        last_reviewed="2026-05-12",
        tags=["jobs", "public-listings", "stealth-required"],
    ),
    "indeed": SourceCompliance(
        source="indeed",
        risk_level=RiskLevel.medium,
        tos_url="https://www.indeed.com/legal",
        scraping_allowed=True,
        api_available=False,
        api_rate_limits="N/A — HTML scraping only; be polite (<10 req/min)",
        robots_txt_status="allowed",
        requires_auth=False,
        data_retention_days=60,
        notes="Indeed India (in.indeed.com) job listings are public and indexed by search engines. Indeed has internal salary/JSON APIs used by the web UI — intercepting them is a grey area. Prefer HTML parsing. Indeed deploys CAPTCHA at high volumes; implement progressive delays and IP rotation if needed.",
        last_reviewed="2026-05-12",
        tags=["jobs", "india", "public-listings"],
    ),
    "stackoverflow": SourceCompliance(
        source="stackoverflow",
        risk_level=RiskLevel.low,
        tos_url="https://stackoverflow.com/legal/terms-of-service",
        scraping_allowed=True,
        api_available=True,
        api_rate_limits="300 req/day (no key), 10K req/day (with API key)",
        robots_txt_status="allowed",
        requires_auth=False,
        data_retention_days=90,
        notes="Stack Exchange data is CC-BY-SA licensed. API is well-documented. Job/tech-stack signals from questions/tags are fair use. Attribute if republishing.",
        last_reviewed="2026-05-08",
        tags=["api", "public-data", "developer"],
    ),
        # ── Niche Job Platforms (14) ────────────────────────────────────────────
        "monster": SourceCompliance(
            source="monster",
            risk_level=RiskLevel.medium,
            tos_url="https://www.monsterindia.com/monster-terms-of-use.html",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Monster India job listings are publicly accessible. Respect robots.txt and rate-limit scraping.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "india"],
        ),
        "naukrigulf": SourceCompliance(
            source="naukrigulf",
            risk_level=RiskLevel.medium,
            tos_url="https://www.naukrigulf.com/terms-and-conditions",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="NaukriGulf (Gulf region) job listings. Public job board data. Respect rate limits.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "gulf"],
        ),
        "freshersworld": SourceCompliance(
            source="freshersworld",
            risk_level=RiskLevel.medium,
            tos_url="https://www.freshersworld.com/terms",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Freshersworld targets entry-level jobs. Public listings, polite scraping. No API available.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "freshers", "india"],
        ),
        "hirist": SourceCompliance(
            source="hirist",
            risk_level=RiskLevel.medium,
            tos_url="https://www.hirist.com/terms/",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Hirist is a tech-focused job platform in India. Public job board data. Rate-limit scraping.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "tech", "india"],
        ),
        "cutshort": SourceCompliance(
            source="cutshort",
            risk_level=RiskLevel.medium,
            tos_url="https://cutshort.com/terms",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="CutShort is a curated tech hiring platform. Public listings. Use polite scraping with delays.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "tech", "india"],
        ),
        "instahyre": SourceCompliance(
            source="instahyre",
            risk_level=RiskLevel.medium,
            tos_url="https://www.instahyre.com/terms-of-use/",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Instahyre is an AI-driven job platform. Public listings. Respect rate limits.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "ai", "india"],
        ),
        "hirect": SourceCompliance(
            source="hirect",
            risk_level=RiskLevel.medium,
            tos_url="https://www.hirect.in/terms-and-conditions",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Hirect is a direct-hire chat-based job platform. Public job listings.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "direct-hire", "india"],
        ),
        "weekday": SourceCompliance(
            source="weekday",
            risk_level=RiskLevel.medium,
            tos_url="https://www.weekday.work/terms",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Weekday is a curated tech hiring platform. Public listings. Rate-limit scraping.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "tech", "india"],
        ),
        "timesjobs": SourceCompliance(
            source="timesjobs",
            risk_level=RiskLevel.medium,
            tos_url="https://www.timesjobs.com/terms-of-use",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="TimesJobs is a leading Indian job board. Public job data. Respect robots.txt.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "india"],
        ),
        "foundit": SourceCompliance(
            source="foundit",
            risk_level=RiskLevel.medium,
            tos_url="https://www.foundit.in/terms-of-use",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="Foundit (formerly Monster India/APAC) job listings. Public board data.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "india", "apac"],
        ),
        "sarkari_result": SourceCompliance(
            source="sarkari_result",
            risk_level=RiskLevel.low,
            tos_url="https://www.sarkariresult.com/",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no API",
            robots_txt_status="allowed",
            requires_auth=False,
            data_retention_days=90,
            notes="Sarkari Result publishes government job notifications. Public data, no ToS restrictions on listings.",
            last_reviewed="2026-05-12",
            tags=["government-jobs", "india"],
        ),
        "freejobalert": SourceCompliance(
            source="freejobalert",
            risk_level=RiskLevel.low,
            tos_url="https://www.freejobalert.com/",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no API",
            robots_txt_status="allowed",
            requires_auth=False,
            data_retention_days=90,
            notes="FreeJobAlert aggregates government and public sector job notifications. Public data.",
            last_reviewed="2026-05-12",
            tags=["government-jobs", "india"],
        ),
        "employment_news": SourceCompliance(
            source="employment_news",
            risk_level=RiskLevel.low,
            tos_url="https://www.employmentnews.gov.in/",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no API",
            robots_txt_status="allowed",
            requires_auth=False,
            data_retention_days=90,
            notes="Employment News is the Indian government's official employment newspaper. Public domain government job listings.",
            last_reviewed="2026-05-12",
            tags=["government-jobs", "india", "official"],
        ),
        "iimjobs": SourceCompliance(
            source="iimjobs",
            risk_level=RiskLevel.medium,
            tos_url="https://www.iimjobs.com/terms",
            scraping_allowed=True,
            api_available=False,
            api_rate_limits="N/A — no public API",
            robots_txt_status="restricted",
            requires_auth=False,
            data_retention_days=30,
            notes="IIMJobs targets management professionals. Public job listings. Rate-limit scraping.",
            last_reviewed="2026-05-12",
            tags=["public-jobs", "management", "india"],
        ),
    }


def check_source_compliance(source: str) -> dict[str, Any]:
    """Returns compliance posture for a source. Returns critical-block if unknown."""
    entry = COMPLIANCE_REGISTRY.get(source)
    if entry is None:
        return {
            "source": source,
            "risk_level": RiskLevel.critical.value,
            "scraping_allowed": False,
            "status": "blocked",
            "reason": f"Unknown source '{source}' — not in compliance registry. Add to tos_registry.py before collecting.",
        }
    return {
        "source": entry.source,
        "risk_level": entry.risk_level.value,
        "scraping_allowed": entry.scraping_allowed,
        "api_available": entry.api_available,
        "api_rate_limits": entry.api_rate_limits,
        "requires_auth": entry.requires_auth,
        "data_retention_days": entry.data_retention_days,
        "tos_url": entry.tos_url,
        "notes": entry.notes,
        "last_reviewed": entry.last_reviewed,
        "status": "allowed" if entry.risk_level in (RiskLevel.low, RiskLevel.medium) else "restricted",
    }


def get_blocked_sources() -> list[str]:
    """Returns list of sources at critical risk level (should be disabled)."""
    return [
        s.source
        for s in COMPLIANCE_REGISTRY.values()
        if s.risk_level == RiskLevel.critical
    ]


def get_allowed_sources() -> list[str]:
    """Returns list of sources safe for automated collection."""
    return [
        s.source
        for s in COMPLIANCE_REGISTRY.values()
        if s.risk_level in (RiskLevel.low, RiskLevel.medium)
    ]


def get_compliance_summary() -> dict[str, Any]:
    """Full compliance posture summary for admin dashboard."""
    sources = []
    for s in COMPLIANCE_REGISTRY.values():
        sources.append({
            "source": s.source,
            "risk_level": s.risk_level.value,
            "scraping_allowed": s.scraping_allowed,
            "api_available": s.api_available,
            "requires_auth": s.requires_auth,
        })

    return {
        "total_sources": len(sources),
        "by_risk": {
            "low": len([s for s in COMPLIANCE_REGISTRY.values() if s.risk_level == RiskLevel.low]),
            "medium": len([s for s in COMPLIANCE_REGISTRY.values() if s.risk_level == RiskLevel.medium]),
            "high": len([s for s in COMPLIANCE_REGISTRY.values() if s.risk_level == RiskLevel.high]),
            "critical": len([s for s in COMPLIANCE_REGISTRY.values() if s.risk_level == RiskLevel.critical]),
        },
        "blocked_sources": get_blocked_sources(),
        "allowed_sources": get_allowed_sources(),
        "sources": sources,
    }
