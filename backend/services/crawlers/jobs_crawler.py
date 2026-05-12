"""
backend/services/crawlers/jobs_crawler.py
Aggregates job signals from Naukri + HN Who's Hiring + Reddit and persists to JobSignal table.
Uses lazy imports to avoid hard dependency on Playwright.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.repository import JobSignalRepo
from backend.services.crawlers.base import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)


class JobsCrawler(BaseCrawler):
    """Crawl job platforms → JobSignal table."""

    source = "jobs"

    def __init__(self, keywords: list[str] | None = None, locations: list[str] | None = None) -> None:
        self._keywords = keywords or self._default_keywords()
        self._locations = locations or self._default_locations()

    async def crawl(self, session: AsyncSession) -> CrawlResult:
        result = CrawlResult(source=self.source)
        repo = JobSignalRepo(session)
        persisted = 0
        collected = 0

        # ── Source 1: Naukri (lazy import — requires Playwright) ────────────
        try:
            from backend.collectors.naukri import NaukriCollector

            naukri = NaukriCollector(keywords=self._keywords, locations=self._locations)
            naukri_posts = await naukri.collect()
            for post in naukri_posts:
                try:
                    meta = post.raw_meta or {}
                    experience = ""
                    if meta.get("experience_min") is not None:
                        experience = f"{meta.get('experience_min')}-{meta.get('experience_max', '')} yrs"
                    await repo.upsert({
                        "company_name": meta.get("company_name", post.author or "Unknown"),
                        "title": post.title,
                        "location": meta.get("location"),
                        "work_mode": meta.get("work_mode", "hybrid"),
                        "experience": experience,
                        "skills": meta.get("skills", []),
                        "salary_range": meta.get("salary_range"),
                        "posted_date": datetime.now(UTC),
                        "source": "naukri",
                        "hiring_velocity": min(post.score * 10, 100) if post.score else 50,
                        "trust_score": 7.0,
                    })
                    persisted += 1
                    collected += 1
                except Exception as exc:
                    result.errors.append(f"Naukri upsert failed: {exc}")
            logger.info("naukri_crawl_complete", count=len(naukri_posts))
        except ImportError:
            logger.warning("Playwright not installed — skipping Naukri")
        except Exception as exc:
            result.errors.append(f"Naukri crawl failed: {exc}")
            logger.warning("naukri_crawl_failed", error=str(exc))

        # ── Source 2: HN Who's Hiring + Reddit ──────────────────────────────
        try:
            from backend.services.job_signals import JobSignalDetector

            detector = JobSignalDetector()
            hn_signals = await detector.detect_signals()
            for signal in hn_signals:
                try:
                    await repo.upsert({
                        "company_name": signal.company_name,
                        "title": signal.role,
                        "location": signal.location,
                        "work_mode": "remote" if signal.location == "Remote" else None,
                        "experience": None,
                        "skills": signal.skills,
                        "salary_range": signal.salary_range,
                        "posted_date": datetime.now(UTC),
                        "source": signal.source_name.lower().replace(" ", "_"),
                        "hiring_velocity": signal.hiring_velocity,
                        "trust_score": signal.trust_score,
                    })
                    persisted += 1
                    collected += 1
                except Exception as exc:
                    result.errors.append(f"HN upsert failed: {exc}")
            logger.info("hn_crawl_complete", count=len(hn_signals))
        except Exception as exc:
            result.errors.append(f"HN crawl failed: {exc}")
            logger.warning("hn_crawl_failed", error=str(exc))

        result.items_collected = collected
        result.items_persisted = persisted
        result.status = "success" if persisted > 0 else "partial"
        result.finished_at = datetime.now(UTC)
        return result

    @staticmethod
    def _default_keywords() -> list[str]:
        return [
            "software-engineer", "data-scientist", "product-manager",
            "devops-engineer", "machine-learning-engineer",
        ]

    @staticmethod
    def _default_locations() -> list[str]:
        return ["bangalore", "mumbai", "pune", "hyderabad", "delhi", "gurgaon", "chennai"]