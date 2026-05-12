"""
collectors/hn.py — Hacker News collector via public Algolia Search API.
No credentials required.
Targets: Ask HN, Show HN, and keyword search for pain-signal keywords.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from backend.collectors.base import BaseCollector, RawPost

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
PAIN_QUERIES = [
    "Ask HN: looking for",
    "Ask HN: recommend",
    "Ask HN: how do you",
    "frustrated with",
    "switched from",
    "alternatives to",
]


class HNCollector(BaseCollector):
    source = "hn"

    def __init__(self, hits_per_query: int = 20) -> None:
        self._hits = hits_per_query

    async def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for query in PAIN_QUERIES:
                try:
                    resp = await client.get(
                        HN_SEARCH_URL,
                        params={
                            "query": query,
                            "tags": "story",
                            "hitsPerPage": self._hits,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for hit in data.get("hits", []):
                        created = hit.get("created_at_i")
                        posts.append(
                            RawPost(
                                source=self.source,
                                external_id=hit.get("objectID", ""),
                                url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                                title=hit.get("title") or "",
                                body=hit.get("story_text") or "",
                                author=hit.get("author") or "",
                                score=hit.get("points") or 0,
                                collected_at=(
                                    datetime.fromtimestamp(created, tz=UTC)
                                    if created
                                    else datetime.now(UTC)
                                ),
                                raw_meta={
                                    "num_comments": hit.get("num_comments", 0),
                                    "query": query,
                                },
                            )
                        )
                except Exception as exc:
                    logger.warning("HNCollector error for query '%s': %s", query, exc)

        logger.info("HNCollector fetched %d posts", len(posts))
        return posts
