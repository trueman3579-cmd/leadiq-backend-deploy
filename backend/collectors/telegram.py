"""
collectors/telegram.py — Telegram channel scraper using Telethon MTProto API.

Targets Indian startup/funding Telegram channels for funding announcements,
hiring signals, product launches, and expansion news.

Uses Telethon (MTProto API) for inbound message scraping, not python-telegram-bot.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any


from backend.collectors.base import BaseCollector, RawPost
from backend.shared.config import settings

logger = logging.getLogger(__name__)

# ── Target Channels (India-focused startup/funding) ──────────────────────────
TARGET_CHANNELS: list[dict[str, str | float]] = [
    {"handle": "inc42official", "category": "funding_news", "trust": 0.80},
    {"handle": "yourstoryofficial", "category": "funding_news", "trust": 0.78},
    {"handle": "dealflow", "category": "funding_news", "trust": 0.82},
    {"handle": "foundingfuel", "category": "funding_news", "trust": 0.75},
    {"handle": "yourstoryhub", "category": "funding_news", "trust": 0.72},
    {"handle": "YourStoryIndia", "category": "funding_news", "trust": 0.70},
    {"handle": "AnalyticsIndia", "category": "tech_news", "trust": 0.68},
    {"handle": "Inc42Mag", "category": "tech_news", "trust": 0.70},
    {"handle": "YourStoryTeam", "category": "funding_news", "trust": 0.75},
    {"handle": "YourStoryStartups", "category": "funding_news", "trust": 0.72},
    {"handle": "YourStoryVC", "category": "funding_news", "trust": 0.80},
    {"handle": "YourStoryInvest", "category": "funding_news", "trust": 0.78},
    {"handle": "YourStoryMedia", "category": "media", "trust": 0.70},
    {"handle": "YourStoryJobs", "category": "hiring", "trust": 0.65},
]

# ── Signal Keywords (for pre-filtering lead-relevant messages) ─────────────────
SIGNAL_KEYWORDS: list[str] = [
    "funding",
    "investment",
    "series",
    "seed",
    "pre-seed",
    "round",
    "raise",
    "raised",
    "fund",
    "invested",
    "investor",
    "vc",
    "startup",
    "launch",
    "launched",
    "product",
    "hiring",
    "hire",
    "job",
    "job opening",
    "position",
    "expansion",
    "launching",
    "announces",
    "announce",
    "new product",
    "funds",
    " Series ",
    "Series A",
    "Series B",
    "Series C",
    "pre Series",
]

# ── Regex Extractors (zero LLM cost) ──────────────────────────────────────────
EMAIL_RE = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
URL_RE = re.compile(r'https?://[^\s<]+')
LINKEDIN_RE = re.compile(r'linkedin\.com/in/[^\s<]+', re.IGNORECASE)
TWITTER_RE = re.compile(r'@?twitter\.com/[^\s<]+', re.IGNORECASE)
FUNDING_AMOUNT_RE = re.compile(
    r'(Rs\.\s*[\d,]+(?:\s*crore)?|USD\s*[\d.]+\s*(?:million|crore)?|₹\s*[\d,]+(?:\s*crore)?)',
    re.IGNORECASE
)
TECH_STACK_RE = re.compile(
    r'(Python|Node\.js|React|Go|Java|Kotlin|Swift|TypeScript|Docker|AWS|GCP|Azure)',
    re.IGNORECASE
)
LOCATION_RE = re.compile(
    r'(Bangalore|Bengaluru|Hyderabad|Delhi|Mumbai|Pune|Chennai|Gurgaon|Noida|Gurugram|Ahmedabad|Jaipur|Surat|Kochi)',
    re.IGNORECASE
)


def has_lead_signal(text: str) -> bool:
    """Check if message contains lead-relevant signals."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in SIGNAL_KEYWORDS)


def extract_signals(text: str) -> dict[str, Any]:
    """Extract lead signals from message text using regex."""
    signals = {
        "emails": [],
        "urls": [],
        "linkedin": [],
        "twitter": [],
        "funding_amounts": [],
        "tech_stack": [],
        "locations": [],
    }

    signals["emails"] = EMAIL_RE.findall(text)
    signals["urls"] = URL_RE.findall(text)
    signals["linkedin"] = LINKEDIN_RE.findall(text)
    signals["twitter"] = TWITTER_RE.findall(text)
    signals["funding_amounts"] = FUNDING_AMOUNT_RE.findall(text)
    signals["tech_stack"] = TECH_STACK_RE.findall(text)
    signals["locations"] = LOCATION_RE.findall(text)

    return signals


def make_message_hash(source: str, external_id: str, content: str) -> str:
    """Create MD5 hash for message deduplication."""
    canonical = f"{source}:{external_id}:{content.strip().lower()}"
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


class TelegramCollector(BaseCollector):
    """Collect lead intelligence from public Telegram channels."""

    source = "telegram"

    def __init__(
        self,
        channels: list[dict[str, str | float]] | None = None,
        limit_per_channel: int = 5,
        min_signal_score: float = 0.5,
    ) -> None:
        self._channels = channels or TARGET_CHANNELS
        self._limit_per_channel = limit_per_channel
        self._min_signal_score = min_signal_score

    async def collect(self) -> list[RawPost]:
        """Fetch lead intelligence from Telegram channels."""
        if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
            logger.warning(
                "TELEGRAM_API_ID or TELEGRAM_API_HASH not set — skipping TelegramCollector"
            )
            return []

        try:
            from telethon import TelegramClient
            from telethon.errors import FloodWaitError
        except ImportError:
            logger.error("telethon is not installed")
            return []

        posts: list[RawPost] = []

        # Create client (using user account for public channel reading)
        client = TelegramClient(
            "leadiq_telegram",
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )

        try:
            await client.start()
        except Exception as exc:
            logger.error("Failed to start Telegram client: %s", exc)
            return []

        try:
            for channel_info in self._channels:
                handle = channel_info["handle"]
                category = channel_info.get("category", "other")
                trust = float(channel_info.get("trust", 0.70))

                try:
                    # Get entity for the channel
                    try:
                        entity = await client.get_entity(handle)
                    except Exception as exc:
                        logger.warning(
                            "TelegramCollector: could not get entity for %s: %s",
                            handle,
                            exc,
                        )
                        continue

                    # Fetch messages with pagination
                    messages = []
                    async for message in client.iter_messages(
                        entity,
                        limit=self._limit_per_channel,
                        reverse=True,  # Oldest first for consistency
                    ):
                        if message.message:
                            messages.append(message)

                    for msg in messages:
                        # Pre-filter by signal keywords
                        if not has_lead_signal(msg.message or ""):
                            continue

                        # Extract signals
                        signals = extract_signals(msg.message or "")

                        # Calculate confidence based on signals found
                        confidence = self._calculate_confidence(
                            signals=signals,
                            source_trust=trust,
                        )

                        # Build external_id from message metadata
                        external_id = f"{handle}:{msg.id}"

                        posts.append(
                            RawPost(
                                source=self.source,
                                external_id=external_id,
                                url=f"https://t.me/{handle}/{msg.id}",
                                title=self._extract_title(
                                    msg.message or "",
                                    signals=signals,
                                ),
                                body=msg.message or "",
                                author=handle,
                                score=int(msg.views or 0),
                                collected_at=datetime.now(UTC),
                                raw_meta={
                                    "channel": handle,
                                    "category": category,
                                    "message_id": msg.id,
                                    "views": msg.views or 0,
                                    "date": msg.date.isoformat()
                                    if msg.date
                                    else None,
                                    "signals": signals,
                                    "confidence": confidence,
                                    "source_trust": trust,
                                },
                            )
                        )

                except FloodWaitError as exc:
                    logger.warning(
                        "TelegramCollector FloodWait for %s: %s seconds",
                        handle,
                        exc.seconds,
                    )
                    await asyncio.sleep(exc.seconds)
                    continue
                except Exception as exc:
                    logger.warning(
                        "TelegramCollector error for %s: %s",
                        handle,
                        exc,
                    )
                    continue

        finally:
            await client.disconnect()

        logger.info(
            "TelegramCollector fetched %d posts from %d channels",
            len(posts),
            len(self._channels),
        )
        return posts

    def _calculate_confidence(
        self, signals: dict[str, Any], source_trust: float
    ) -> float:
        """Calculate confidence score based on signals and source trust.

        Formula:
        - Base: source_trust
        - +0.15 if email found
        - +0.10 if funding amount found
        - +0.10 if URL found
        - +0.05 if LinkedIn found
        - +0.05 if tech stack found
        - +0.05 if location found
        - Max 0.95 (to leave room for human verification)
        """
        confidence = source_trust

        if signals["emails"]:
            confidence += 0.15
        if signals["funding_amounts"]:
            confidence += 0.10
        if signals["urls"]:
            confidence += 0.10
        if signals["linkedin"]:
            confidence += 0.05
        if signals["tech_stack"]:
            confidence += 0.05
        if signals["locations"]:
            confidence += 0.05

        return min(confidence, 0.95)

    def _extract_title(self, body: str, signals: dict[str, Any]) -> str:
        """Generate a title from the message body."""
        # Priority: Company name from URL > Funding announcement > First line
        if signals["urls"]:
            url = signals["urls"][0]
            # Extract domain as title
            domain = url.replace("https://", "").replace("http://", "").split("/")[0]
            return f"Funding/Announcement: {domain}"

        if signals["funding_amounts"]:
            amount = signals["funding_amounts"][0]
            return f"Funding Raised: {amount}"

        # Fallback: First 50 chars of message
        return (body[:50] + "...") if len(body) > 50 else body


# ── Convenience function ────────────────────────────────────────────────────────


async def collect_telegram_leads(
    channels: list[dict[str, str | float]] | None = None,
) -> list[RawPost]:
    """Convenience function to collect Telegram leads."""
    collector = TelegramCollector(channels=channels)
    return await collector.collect()
