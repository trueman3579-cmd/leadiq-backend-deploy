"""
ingestion/collectors.py — Collector factory and configuration.

Provides unified access to all collectors and handles their configuration.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import structlog

from backend.shared.config import settings

if TYPE_CHECKING:
    from backend.collectors.base import BaseCollector

# Hibernated sources — excluded from normal ingestion
# while their functionality is verified or replaced.
_HIBERNATED: set[str] = set()
_DEFAULT_DISABLED: set[str] = {"dpiit_v2", "mca21", "msme", "gem"}
logger = structlog.get_logger(__name__)


def is_hibernated(source: str) -> bool:
    """Check if a source is hibernated (excluded from ingestion)."""
    return source in _HIBERNATED or source in settings.disabled_sources


def get_collectors(
    mode: str = "b2b_sales",
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> list[BaseCollector]:
    """
    Get all configured collectors for ingestion.

    Args:
        mode: Profile mode for adaptive collection (e.g., "b2b_sales", "hiring")
        include_keywords: Keywords to filter for (optional)
        exclude_keywords: Keywords to filter out (optional)

    Returns:
        List of configured collector instances
    """
    # Core / Community
    from backend.collectors.reddit import RedditCollector
    from backend.collectors.hn import HNCollector
    from backend.collectors.twitter import TwitterCollector
    from backend.collectors.rss import RSSCollector
    from backend.collectors.github import GithubCollector
    from backend.collectors.github_issues import GitHubIssuesCollector
    from backend.collectors.producthunt import ProductHuntCollector
    from backend.collectors.stackoverflow import StackOverflowCollector
    from backend.collectors.telegram import TelegramCollector

    # Jobs
    from backend.collectors.naukri import NaukriCollector
    from backend.collectors.internshala import InternshalaCollector
    from backend.collectors.indeed import IndeedCollector
    from backend.collectors.linkedin_jobs import LinkedInJobsCollector
    from backend.collectors.cutshort import CutshortCollector
    from backend.collectors.foundit import FounditCollector
    from backend.collectors.freejobalert import FreeJobAlertCollector
    from backend.collectors.freshersworld import FreshersworldCollector
    from backend.collectors.hirect import HirectCollector
    from backend.collectors.hirist import HiristCollector
    from backend.collectors.iimjobs import IIMJobsCollector
    from backend.collectors.instahyre import InstahyreCollector
    from backend.collectors.monster import MonsterCollector
    from backend.collectors.naukrigulf import NaukriGulfCollector
    from backend.collectors.sarkari_result import SarkariResultCollector
    from backend.collectors.shine import ShineCollector
    from backend.collectors.timesjobs import TimesJobsCollector
    from backend.collectors.weekday import WeekdayCollector
    from backend.collectors.employment_news import EmploymentNewsCollector

    # Government / Funding
    from backend.collectors.dpiit_v2 import DPIITv2Collector
    from backend.collectors.mca21_v2 import MCA21Collector
    from backend.collectors.msme import MSMECollector
    from backend.collectors.gem import GeMCollector

    # Scrapling / Advanced
    )

    # Determine subreddits and queries based on mode
    if include_keywords or exclude_keywords:
        from backend.services.personalization import QueryGenerator
        qg = QueryGenerator()
        reddit_queries = qg.generate_reddit_queries(
            mode=mode,
            include_keywords=include_keywords or [],
            target_industries=[],
            hiring_roles=[],
            skills=[],
        )
        reddit_subs = qg.generate_subreddits(
            mode=mode,
            target_industries=[],
        )
    else:
        reddit_queries = None
        reddit_subs = None

    all_collectors: list[BaseCollector] = [
        # Core / Community
        RedditCollector(
            subreddits=reddit_subs,
            search_queries=reddit_queries,
        ) if reddit_queries else RedditCollector(),
        HNCollector(),
        TwitterCollector(),
        RSSCollector(),
        GithubCollector(),
        GitHubIssuesCollector(),
        ProductHuntCollector(),
        StackOverflowCollector(),
        TelegramCollector(),
        # Jobs
        NaukriCollector(),
        InternshalaCollector(),
        IndeedCollector(),
        LinkedInJobsCollector(),
        CutshortCollector(),
        FounditCollector(),
        FreeJobAlertCollector(),
        FreshersworldCollector(),
        HirectCollector(),
        HiristCollector(),
        IIMJobsCollector(),
        InstahyreCollector(),
        MonsterCollector(),
        NaukriGulfCollector(),
        SarkariResultCollector(),
        ShineCollector(),
        TimesJobsCollector(),
        WeekdayCollector(),
        EmploymentNewsCollector(),
        # Government / Funding
        DPIITv2Collector(),
        MCA21Collector(),
        MSMECollector(),
        GeMCollector(),
        # Scrapling / Advanced
    ]

    disabled_sources = _HIBERNATED | _DEFAULT_DISABLED | settings.disabled_sources
    filtered: list[BaseCollector] = []
    for collector in all_collectors:
        if collector.source in disabled_sources:
            logger.info("collector_disabled", source=collector.source, reason="disabled_source_policy")
            continue
        filtered.append(collector)
    return filtered


def get_source_names() -> list[str]:
    """Get list of all active (non-hibernated) source names in ingestion order."""
    all_sources = [
        # Core / Community
        "reddit",
        "hn",
        "twitter",
        "rss",
        "github",
        "github_issues",
        "producthunt",
        "stackoverflow",
        "telegram",
        # Jobs
        "naukri",
        "internshala",
        "indeed",
        "linkedin_jobs",
        "cutshort",
        "foundit",
        "freejobalert",
        "freshersworld",
        "hirect",
        "hirist",
        "iimjobs",
        "instahyre",
        "monster",
        "naukrigulf",
        "sarkari_result",
        "shine",
        "timesjobs",
        "weekday",
        "employment_news",
        # Government / Funding
        "dpiit_v2",
        "mca21",
        "msme",
        "gem",
        # Scrapling / Advanced
        "linkedin",
        "angellist",
        "crunchbase",
    ]
    disabled_sources = _HIBERNATED | _DEFAULT_DISABLED | settings.disabled_sources
    return [s for s in all_sources if s not in disabled_sources]


def get_collector_by_source(source: str) -> type:
    """Get collector class by source name."""
    # Core / Community
    from backend.collectors.reddit import RedditCollector
    from backend.collectors.hn import HNCollector
    from backend.collectors.twitter import TwitterCollector
    from backend.collectors.rss import RSSCollector
    from backend.collectors.github import GithubCollector
    from backend.collectors.github_issues import GitHubIssuesCollector
    from backend.collectors.producthunt import ProductHuntCollector
    from backend.collectors.stackoverflow import StackOverflowCollector
    from backend.collectors.telegram import TelegramCollector

    # Jobs
    from backend.collectors.naukri import NaukriCollector
    from backend.collectors.internshala import InternshalaCollector
    from backend.collectors.indeed import IndeedCollector
    from backend.collectors.linkedin_jobs import LinkedInJobsCollector
    from backend.collectors.cutshort import CutshortCollector
    from backend.collectors.foundit import FounditCollector
    from backend.collectors.freejobalert import FreeJobAlertCollector
    from backend.collectors.freshersworld import FreshersworldCollector
    from backend.collectors.hirect import HirectCollector
    from backend.collectors.hirist import HiristCollector
    from backend.collectors.iimjobs import IIMJobsCollector
    from backend.collectors.instahyre import InstahyreCollector
    from backend.collectors.monster import MonsterCollector
    from backend.collectors.naukrigulf import NaukriGulfCollector
    from backend.collectors.sarkari_result import SarkariResultCollector
    from backend.collectors.shine import ShineCollector
    from backend.collectors.timesjobs import TimesJobsCollector
    from backend.collectors.weekday import WeekdayCollector
    from backend.collectors.employment_news import EmploymentNewsCollector

    # Government / Funding
    from backend.collectors.dpiit_v2 import DPIITv2Collector
    from backend.collectors.mca21_v2 import MCA21Collector
    from backend.collectors.msme import MSMECollector
    from backend.collectors.gem import GeMCollector

    # Scrapling / Advanced
    )

    mapping = {
        # Core / Community
        "reddit": RedditCollector,
        "hn": HNCollector,
        "twitter": TwitterCollector,
        "rss": RSSCollector,
        "github": GithubCollector,
        "github_issues": GitHubIssuesCollector,
        "producthunt": ProductHuntCollector,
        "stackoverflow": StackOverflowCollector,
        "telegram": TelegramCollector,
        # Jobs
        "naukri": NaukriCollector,
        "internshala": InternshalaCollector,
        "indeed": IndeedCollector,
        "linkedin_jobs": LinkedInJobsCollector,
        "cutshort": CutshortCollector,
        "foundit": FounditCollector,
        "freejobalert": FreeJobAlertCollector,
        "freshersworld": FreshersworldCollector,
        "hirect": HirectCollector,
        "hirist": HiristCollector,
        "iimjobs": IIMJobsCollector,
        "instahyre": InstahyreCollector,
        "monster": MonsterCollector,
        "naukrigulf": NaukriGulfCollector,
        "sarkari_result": SarkariResultCollector,
        "shine": ShineCollector,
        "timesjobs": TimesJobsCollector,
        "weekday": WeekdayCollector,
        "employment_news": EmploymentNewsCollector,
        # Government / Funding
        "dpiit_v2": DPIITv2Collector,
        "mca21": MCA21Collector,
        "msme": MSMECollector,
        "gem": GeMCollector,
        # Scrapling / Advanced
    }
    if source not in mapping:
        raise ValueError(f"Unknown source: {source}. Available: {list(mapping.keys())}")
    if is_hibernated(source):
        raise ValueError(
            f"Source '{source}' is hibernated and cannot be used. "
            f"Active sources: {get_source_names()}"
        )
    return mapping[source]
