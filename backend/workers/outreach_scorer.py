"""
outreach_scorer.py — Outreach Draft Quality Gate (Day 20)
Scores outreach drafts 0.0-10.0 for specificity.
Hard gate: if score < 7.0, the pipeline REFUSES to emit the draft.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

MIN_SPECIFICITY_SCORE = 7.0
MAX_SCORE = 10.0

PENALTY_PHRASES = [
    "i noticed your post",
    "i came across your",
    "reaching out",
    "i hope this finds you",
    "just wanted to",
    "checking in",
    "touching base",
    "let me know if",
    "would love to connect",
    "synergies",
]

SIGNAL_REWARDS = {
    "mentions_intent": 1.5,
    "mentions_pain_word": 1.5,
    "has_question": 1.0,
    "has_number": 1.0,
    "has_company_ref": 1.5,
    "has_time_reference": 1.0,
    "is_under_100_words": 0.5,
    "no_spam_opener": 1.0,
}


def score_outreach_draft(draft: str | None, source_text: str = "", intent: str = "") -> float:
    """Score outreach draft specificity from 0.0 to 10.0."""
    if draft is None or len(draft.strip()) < 20:
        return 0.0

    score = 4.0
    draft_lower = draft.lower()
    source_lower = source_text.lower() if source_text else ""

    for phrase in PENALTY_PHRASES:
        if phrase in draft_lower:
            score -= 0.5

    if intent and intent.lower() in draft_lower:
        score += SIGNAL_REWARDS["mentions_intent"]

    if source_lower:
        source_words = [
            w for w in re.findall(r"\b\w{5,}\b", source_lower)
            if w not in {"about", "their", "there", "which", "would", "could", "should", "these", "those"}
        ]
        if source_words and any(w in draft_lower for w in source_words):
            score += SIGNAL_REWARDS["mentions_pain_word"]

    if "?" in draft:
        score += SIGNAL_REWARDS["has_question"]

    if any(c.isdigit() for c in draft) or "%" in draft or "$" in draft:
        score += SIGNAL_REWARDS["has_number"]

    time_words = ["week", "q2", "q3", "q1", "month", "days", "deadline", "tomorrow", "today"]
    if any(w in draft_lower for w in time_words):
        score += SIGNAL_REWARDS["has_time_reference"]

    if len(draft.split()) < 100:
        score += SIGNAL_REWARDS["is_under_100_words"]

    spam_openers = PENALTY_PHRASES[:4]
    if not any(opener in draft_lower for opener in spam_openers):
        score += SIGNAL_REWARDS["no_spam_opener"]

    return max(0.0, min(MAX_SCORE, score))


def gate_outreach(draft: str | None, source_text: str = "", intent: str = "") -> tuple[str | None, float]:
    """Hard gate: returns (draft, score) only if score >= 7.0."""
    score = score_outreach_draft(draft, source_text, intent)
    if score >= MIN_SPECIFICITY_SCORE:
        return draft, score
    else:
        logger.info("outreach_refused score=%.2f", score)
        return None, score
