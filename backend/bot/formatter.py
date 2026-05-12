"""
bot/formatter.py — Convert lead records to Telegram-safe HTML messages.
"""
from __future__ import annotations

from html import escape
from collections.abc import Sequence


def format_lead_message(lead) -> str:
    score = getattr(lead, "final_score", 0)
    company = getattr(lead, "company_name", None) or "Unknown company"
    contact = getattr(lead, "contact_name", None) or "Unknown contact"
    intent = getattr(lead, "intent", "other")
    urgency = getattr(lead, "urgency", "low")
    draft = getattr(lead, "outreach_draft", None) or "No draft generated"

    return (
        f"<b>Hot Lead: {escape(company)}</b>\n"
        f"Score: <b>{score:.1f}</b>\n"
        f"Contact: {escape(contact)}\n"
        f"Intent: {escape(intent)} | Urgency: {escape(urgency)}\n\n"
        f"<b>Outreach draft</b>\n{escape(draft)}"
    )


def format_stats_message(leads: Sequence) -> str:
    total = len(leads)
    hot = sum(1 for l in leads if getattr(l, "final_score", 0) >= 80)
    warm = sum(1 for l in leads if 60 <= getattr(l, "final_score", 0) < 80)
    avg = sum(getattr(l, "final_score", 0) for l in leads) / total if total else 0
    return (
        "<b>LeadIQ Pipeline Stats</b>\n"
        f"Total leads: <b>{total}</b>\n"
        f"Hot leads: <b>{hot}</b>\n"
        f"Warm leads: <b>{warm}</b>\n"
        f"Avg score: <b>{avg:.1f}</b>"
    )
