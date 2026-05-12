"""
collectors/rss.py — RSS/Atom feed collector via feedparser.
No credentials required.
Configure FEED_URLS to target industry-specific publications and blogs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from backend.collectors.base import BaseCollector, RawPost

logger = logging.getLogger(__name__)

FEED_URLS: list[str] = [
    "https://feeds.feedburner.com/TechCrunch",
    "https://www.indiehackers.com/feed.rss",
    "https://news.ycombinator.com/rss",
    "https://blog.ycombinator.com/feed/",
    "https://feeds.feedburner.com/PaulGraham",
    "https://hackernoon.com/feed",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
]


class RSSCollector(BaseCollector):
    source = "rss"

    def __init__(self, max_entries_per_feed: int = 15) -> None:
        self._max = max_entries_per_feed

    async def collect(self) -> list[RawPost]:
        try:
            import feedparser  # type: ignore
        except ImportError:
            logger.error("feedparser not installed — run: pip install feedparser")
            return []

        loop = asyncio.get_event_loop()
        posts: list[RawPost] = []

        def _fetch_feed(url: str) -> list[RawPost]:
            result: list[RawPost] = []
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[: self._max]:
                    published = _parse_date(entry.get("published") or entry.get("updated"))
                    content = (
                        entry.get("summary")
                        or entry.get("description")
                        or entry.get("content", [{}])[0].get("value", "")
                    )
                    result.append(
                        RawPost(
                            source=self.source,
                            external_id=entry.get("id") or entry.get("link") or entry.get("title", ""),
                            url=entry.get("link") or url,
                            title=entry.get("title") or "",
                            body=content,
                            author=entry.get("author") or feed.feed.get("title") or "",
                            collected_at=published,
                            raw_meta={"feed_url": url, "feed_title": feed.feed.get("title", "")},
                        )
                    )
            except Exception as exc:
                logger.warning("RSSCollector error for %s: %s", url, exc)
            return result

        tasks = [loop.run_in_executor(None, _fetch_feed, url) for url in FEED_URLS]
        results = await asyncio.gather(*tasks)
        for r in results:
            posts.extend(r)

        logger.info("RSSCollector fetched %d entries", len(posts))
        return posts


def _parse_date(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    try:
        return parsedate_to_datetime(raw).astimezone(UTC)
    except Exception:
        return datetime.now(UTC)
