"""
collectors/twitter.py — Twitter/X collector via official API v2 (bearer token).
Env vars required: TWITTER_BEARER_TOKEN

Searches recent tweets for ICP pain-signal keywords.
Filters out retweets and quote tweets to focus on original intent signals.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from backend.collectors.base import BaseCollector, RawPost
from backend.shared.config import settings

logger = logging.getLogger(__name__)

TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
SEARCH_QUERIES = [
    "looking for software -is:retweet -is:quote",
    "anyone recommend tool -is:retweet -is:quote",
    "frustrated with platform -is:retweet -is:quote",
    "switched from SaaS -is:retweet -is:quote",
    "need alternative to -is:retweet -is:quote",
    "pain point workflow -is:retweet -is:quote",
]
TWEET_FIELDS = "id,text,author_id,created_at,public_metrics,entities"
EXPANSIONS = "author_id"
USER_FIELDS = "username,name"


class TwitterCollector(BaseCollector):
    source = "twitter"

    def __init__(self, max_results_per_query: int = 20) -> None:
        self._max = min(max_results_per_query, 100)  # API max is 100

    async def collect(self) -> list[RawPost]:
        if not settings.TWITTER_BEARER_TOKEN:
            logger.warning("TWITTER_BEARER_TOKEN not set — skipping TwitterCollector")
            return []

        headers = {"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"}
        start_time = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in SEARCH_QUERIES:
                try:
                    resp = await client.get(
                        TWITTER_SEARCH_URL,
                        headers=headers,
                        params={
                            "query": query,
                            "max_results": self._max,
                            "tweet.fields": TWEET_FIELDS,
                            "expansions": EXPANSIONS,
                            "user.fields": USER_FIELDS,
                            "start_time": start_time,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    users_by_id: dict[str, dict] = {
                        u["id"]: u
                        for u in data.get("includes", {}).get("users", [])
                    }

                    for tweet in data.get("data", []):
                        author_id = tweet.get("author_id", "")
                        user = users_by_id.get(author_id, {})
                        metrics = tweet.get("public_metrics", {})
                        posts.append(
                            RawPost(
                                source=self.source,
                                external_id=tweet["id"],
                                url=f"https://twitter.com/i/web/status/{tweet['id']}",
                                title="",
                                body=tweet.get("text", ""),
                                author=user.get("username", author_id),
                                score=metrics.get("like_count", 0),
                                collected_at=datetime.fromisoformat(
                                    tweet["created_at"].replace("Z", "+00:00")
                                ),
                                raw_meta={
                                    "query": query,
                                    "retweet_count": metrics.get("retweet_count", 0),
                                    "reply_count": metrics.get("reply_count", 0),
                                    "impression_count": metrics.get("impression_count", 0),
                                    "author_name": user.get("name", ""),
                                },
                            )
                        )
                except httpx.HTTPStatusError as exc:
                    logger.warning("TwitterCollector HTTP error for query '%s': %s", query, exc.response.status_code)
                except Exception as exc:
                    logger.warning("TwitterCollector error for query '%s': %s", query, exc)

        logger.info("TwitterCollector fetched %d tweets", len(posts))
        return posts
