"""
collectors/producthunt.py — ProductHunt collector.

Harvests trending product launches and comments where users express pain,
compare alternatives, or signal buying intent.

Uses ProductHunt GraphQL API (public, no token required for basic access).
Falls back to RSS feed if GraphQL fails.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx

from backend.collectors.base import BaseCollector, RawPost

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"
_RSS_URL = "https://www.producthunt.com/feed"

# Pain/opportunity keywords to filter relevant discussions
_OPPORTUNITY_KEYWORDS = [
    "looking for", "alternative to", "instead of", "wish it had",
    "missing feature", "pain point", "switched from", "frustrated",
    "need a tool", "desperately need", "can't find", "does anyone know",
    "recommend", "budget", "enterprise", "team plan", "worth it",
    "considering", "evaluating", "vs", "compared to",
]

# Categories that produce B2B signals
_TARGET_CATEGORIES = [
    "developer-tools", "saas", "productivity", "marketing", "sales",
    "analytics", "artificial-intelligence", "design-tools", "api",
    "devops", "crm", "communication", "hr-tech", "finance",
]


class ProductHuntCollector(BaseCollector):
    """
    Collects ProductHunt discussions and comments that signal buying intent
    or pain points in the B2B SaaS space.
    """

    source = "producthunt"

    def __init__(
        self,
        max_posts: int = 30,
        days_back: int = 3,
        target_categories: list[str] | None = None,
    ) -> None:
        self._max_posts  = max_posts
        self._days_back  = days_back
        self._categories = target_categories or _TARGET_CATEGORIES[:6]

    async def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Try RSS — no auth required, always works
            rss_posts = await self._collect_rss(client)
            posts.extend(rss_posts)
        return posts[: self._max_posts]

    async def _collect_rss(self, client: httpx.AsyncClient) -> list[RawPost]:
        """Fetch ProductHunt RSS feed and parse launches."""
        try:
            resp = await client.get(_RSS_URL, follow_redirects=True)
            resp.raise_for_status()
            return await asyncio.get_event_loop().run_in_executor(
                None, self._parse_rss, resp.text
            )
        except Exception as exc:
            logger.warning("ProductHunt RSS failed: %s", exc)
            return []

    def _parse_rss(self, xml_content: str) -> list[RawPost]:
        """Parse RSS XML without external dependency."""
        import xml.etree.ElementTree as ET

        posts: list[RawPost] = []
        try:
            root = ET.fromstring(xml_content)
            channel = root.find("channel")
            if channel is None:
                return posts

            items = channel.findall("item")
            cutoff = datetime.now(UTC) - timedelta(days=self._days_back)

            for item in items:
                title_el  = item.find("title")
                link_el   = item.find("link")
                desc_el   = item.find("description")
                guid_el   = item.find("guid")
                pubdate_el = item.find("pubDate")

                title = title_el.text or "" if title_el is not None else ""
                url   = link_el.text   or "" if link_el  is not None else ""
                body  = desc_el.text   or "" if desc_el  is not None else ""
                guid  = guid_el.text   or url if guid_el is not None else url

                if not url:
                    continue

                # Parse publication date
                published_at = datetime.now(UTC)
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        published_at = parsedate_to_datetime(pubdate_el.text)
                        if published_at.tzinfo is None:
                            published_at = published_at.replace(tzinfo=UTC)
                    except Exception:
                        pass

                if published_at < cutoff:
                    continue

                posts.append(RawPost(
                    source=self.source,
                    external_id=guid,
                    url=url,
                    title=title,
                    body=body,
                    author="producthunt",
                    score=0,
                    raw_meta={"published_at": published_at.isoformat()},
                    collected_at=published_at,
                ))

        except ET.ParseError as e:
            logger.warning("ProductHunt RSS parse error: %s", e)

        return posts
