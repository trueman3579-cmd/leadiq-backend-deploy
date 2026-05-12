"""
collectors/stackoverflow.py — StackOverflow + StackExchange scraper.
Targets: hiring posts, open source tools, architecture discussions.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx

from backend.collectors.base import BaseCollector, RawPost

logger = logging.getLogger(__name__)

STANDARD_TAGS = ["hiring", "career", "architecture", "automation", "b2b"]

class StackOverflowCollector(BaseCollector):
    source = "stackoverflow"

    def __init__(self, pages: int = 3) -> None:
        self._pages = pages

    async def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for tag in STANDARD_TAGS:
                try:
                    for page in range(1, self._pages + 1):
                        resp = await client.get(
                            "https://api.stackexchange.com/2.3/questions",
                            params={
                                "tagged": tag,
                                "pagesize": 50,
                                "page": page,
                                "site": "stackoverflow",
                                "sort": "creation",
                                "filter": "withbody",
                                "key": ""  # free tier, no key needed for public
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        for item in data.get("items", []):
                            posts.append(RawPost(
                                source=self.source,
                                external_id=str(item["question_id"]),
                                url=item["link"],
                                title=item["title"],
                                body=item.get("body", ""),
                                author=str(item.get("owner", {}).get("display_name", "unknown")),
                                score=item["score"],
                                raw_meta={
                                    "tags": item.get("tags", []),
                                    "answer_count": item["answer_count"],
                                    "view_count": item["view_count"],
                                },
                                collected_at=datetime.now(UTC),
                            ))
                except Exception as exc:
                    logger.warning("StackOverflow collector error for tag '%s': %s", tag, exc)
        logger.info("StackOverflowCollector fetched %d posts", len(posts))
        return posts
