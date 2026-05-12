"""
backend/services/crawlers/base.py — Abstract base for all signal crawlers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class CrawlResult:
    """Result of a single crawler run."""
    source: str
    status: str  # success | partial | failed
    items_collected: int = 0
    items_persisted: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class BaseCrawler(ABC):
    """Abstract base for all data crawlers."""

    source: str  # set by subclass

    @abstractmethod
    async def crawl(self, session: AsyncSession) -> CrawlResult:
        """Collect and persist data. Must be async and DB-aware."""
        ...