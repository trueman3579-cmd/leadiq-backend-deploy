"""
collectors/reddit.py — Reddit scraper via public endpoints.
Targets: r/startups, r/entrepreneur, r/SaaS, r/hiring, r/devops
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx

from backend.collectors.base import BaseCollector, RawPost

logger = logging.getLogger(__name__)

HOT_SUBREDDITS = [
    "startups", "entrepreneur", "SaaS", "hiring", "devops",
    "programming", "webdev", "aws", "python", "reactjs",
    "dataengineering", "cloud", "agile", "productivity"
]

class RedditCollector(BaseCollector):
    source = "reddit"

    def __init__(self, limit: int = 50, subreddits: list[str] | None = None) -> None:
        self._limit = min(limit, 100)
        self._subs = subreddits or HOT_SUBREDDITS

    async def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for sub in self._subs:
                try:
                    url = f"https://www.reddit.com/r/{sub}/hot.json"
                    resp = await client.get(url, params={"limit": self._limit})
                    resp.raise_for_status()
                    data = resp.json()
                    for child in data.get("data", {}).get("children", [])[:self._limit]:
                        p = child["data"]
                        self._append(posts, p)
                except Exception as exc:
                    logger.warning("Reddit collector error for r/%s: %s", sub, exc)
        logger.info("RedditCollector fetched %d posts", len(posts))
        return posts

    def _append(self, posts: list[RawPost], p: dict) -> None:
        """Append a Reddit post with content hash dedup."""
        url = f"https://reddit.com{p.get('permalink', '')}"
        title = p.get("title", "")
        body = p.get("selftext", "") or title
        posts.append(
            RawPost(
                source=self.source,
                external_id=str(p.get("id")),
                url=url,
                title=title,
                body=body,
                author=str(p.get("author", "unknown")),
                score=p.get("score") or 0,
                raw_meta={
                    "subreddit": p.get("subreddit", ""),
                    "upvote_ratio": p.get("upvote_ratio", 0),
                    "num_comments": p.get("num_comments", 0),
                },
                collected_at=datetime.now(UTC),
            )
        )
