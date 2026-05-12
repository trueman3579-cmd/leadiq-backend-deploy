"""
bot/notifier.py — Poll scored stream and dispatch top leads to Telegram.
This process runs independently from FastAPI and Celery workers.
"""
from __future__ import annotations

import asyncio
import logging

from backend.shared.config import settings
from backend.shared.stream import redis_stream
from backend.bot.formatter import format_lead_message

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, min_score: float = 80.0) -> None:
        self._min_score = min_score
        self._bot = None

    async def _init_bot(self):
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        try:
            from telegram import Bot
        except ImportError as exc:
            raise RuntimeError("python-telegram-bot is not installed") from exc
        self._bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async def run(self, consumer_name: str = "notifier-1") -> None:
        await self._init_bot()
        await redis_stream.connect()

        stream = settings.STREAM_SCORED
        group = "notifiers"
        await redis_stream.ensure_group(stream, group)

        logger.info("NotificationDispatcher started")
        while True:
            events = await redis_stream.consume_group(stream, group, consumer_name, count=10, block_ms=5000)
            for event in events:
                try:
                    score = float(event.get("final_score", 0.0))
                    if score >= self._min_score:
                        await self._bot.send_message(
                            chat_id=settings.TELEGRAM_CHAT_ID,
                            text=format_lead_message(_EventLeadAdapter(event.data)),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    await redis_stream.ack(stream, group, event.event_id)
                except Exception as exc:
                    logger.error("Notifier failed for event %s: %s", event.event_id, exc)
            await asyncio.sleep(0.2)


class _EventLeadAdapter:
    """Minimal adapter so formatter can read event payload like a Lead object."""

    def __init__(self, data: dict):
        self.final_score = float(data.get("final_score", 0.0))
        self.company_name = data.get("company_name")
        self.contact_name = data.get("contact_name")
        self.intent = data.get("intent", "other")
        self.urgency = data.get("urgency", "low")
        self.outreach_draft = data.get("outreach_draft")
