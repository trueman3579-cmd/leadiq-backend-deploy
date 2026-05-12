"""
bot/handler.py — Telegram bot command registration and handlers.
Commands:
  /start  — welcome + usage
  /hot    — top hot leads
  /stats  — pipeline summary
  /help   — command list
"""
from __future__ import annotations

import logging

from backend.shared.config import settings
from backend.shared.db import get_db_session
from backend.shared.repository import LeadRepo
from backend.bot.formatter import format_lead_message, format_stats_message

logger = logging.getLogger(__name__)


class TelegramHandler:
    def __init__(self) -> None:
        self._app = None

    async def build(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        try:
            from telegram.ext import ApplicationBuilder, CommandHandler
        except ImportError as exc:
            raise RuntimeError("python-telegram-bot is not installed") from exc

        self._app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

        self._app.add_handler(CommandHandler("start", self.start))
        self._app.add_handler(CommandHandler("help", self.help))
        self._app.add_handler(CommandHandler("hot", self.hot))
        self._app.add_handler(CommandHandler("stats", self.stats))
        return self._app

    async def start(self, update, context) -> None:
        await update.message.reply_text(
            "LeadIQ Bot ready. Use /hot to see top opportunities and /stats for pipeline metrics."
        )

    async def help(self, update, context) -> None:
        await update.message.reply_text(
            "Commands:\n"
            "/hot - Show top hot leads\n"
            "/stats - Show pipeline summary\n"
            "/help - Show this message"
        )

    async def hot(self, update, context) -> None:
        async with get_db_session() as session:
            repo = LeadRepo(session)
            leads = await repo.list_all(min_score=80, limit=5, offset=0)
        if not leads:
            await update.message.reply_text("No hot leads right now.")
            return
        for lead in leads:
            await update.message.reply_html(format_lead_message(lead))

    async def stats(self, update, context) -> None:
        async with get_db_session() as session:
            repo = LeadRepo(session)
            leads = await repo.list_all(limit=200)
        await update.message.reply_html(format_stats_message(leads))

    async def run(self) -> None:
        app = await self.build()
        logger.info("Starting Telegram bot polling")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
