"""
collectors/base.py — Abstract base collector + RawPost dataclass.

Every collector must implement:
  async def collect() -> list[RawPost]

RawPost is the canonical structure before deduplication and DB persistence.
Workers receive RawPost fields as StreamEvent payload on lead:collected.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class RawPost:
    """Canonical representation of a scraped item before enrichment."""

    source: str                        # reddit | hn | twitter | rss | github
    external_id: str                   # Platform-native ID (guaranteed unique per source)
    url: str
    title: str = ""
    body: str = ""
    author: str = ""
    score: int = 0                     # upvotes / likes / stars
    raw_meta: dict[str, Any] = field(default_factory=dict)
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def content_hash(self) -> str:
        """SHA-256 of (source + external_id + title + body) for deduplication."""
        canonical = f"{self.source}:{self.external_id}:{self.title}:{self.body}"
        return hashlib.sha256(canonical.strip().lower().encode("utf-8")).hexdigest()

    def to_stream_payload(self) -> dict[str, Any]:
        """Convert to flat string dict suitable for Redis XADD."""
        return {
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "body": self.body,
            "author": self.author,
            "score": str(self.score),
            "content_hash": self.content_hash,
            "collected_at": self.collected_at.isoformat(),
            "raw_meta": self.raw_meta,
        }


class BaseCollector(ABC):
    """Abstract base for all data collectors."""

    source: str  # Must be set by subclass as class attribute
    enabled: bool = True
    requires_env: list[str] = []

    @abstractmethod
    async def collect(self) -> list[RawPost]:
        """Fetch and return new posts. Must NOT block — use async HTTP."""
        ...

    async def run(self) -> list[RawPost]:
        """Entry point: collect -> deduplicate check is done by pipeline.py."""
        return await self.collect()

    async def healthy(self) -> bool:
        """Check if collector can run. Override for env-var checks."""
        return self.enabled
