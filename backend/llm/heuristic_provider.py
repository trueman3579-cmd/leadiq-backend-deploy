"""
llm/heuristic_provider.py — 0-cost rule-based lead extractor.
No API key required. Uses weighted keyword scoring and regex patterns
to extract structured data from raw posts.
"""
from __future__ import annotations

import re
from typing import Any

from backend.llm.provider import LLMProvider

# Scoring weights
HIRING_KEYWORDS = {
    "hiring": 30, "join us": 25, "looking for": 15, "seeking": 15,
    "open role": 20, "positions open": 20, "we're hiring": 30,
    "opportunities": 10, "careers": 8, "apply": 12, "job opening": 18,
    "talent": 8, "engineer": 8, "developer": 6, "remote": 5,
}

CLAUDE_KEYWORDS = {
    "claude": 25, "anthropic": 20, "claude ai": 35, "claude code": 40,
    "coding assistant": 20, "ai assistant": 15, "llm": 10,
}

PAIN_KEYWORDS = {
    "frustrated": 8, "struggling": 7, "wasted": 6, "slow": 4,
    "difficult": 6, "headache": 7, "annoying": 5, "issue": 3,
}

NEGATIVE_SIGNALS = {
    "spam": -50, "not hiring": -40, "not looking": -30, "not interested": -25,
    "joke": -20, "meme": -15, "off topic": -15, "irrelevant": -10,
}

URGENCY_PATTERNS = {
    "asap": 15, "immediately": 15, "urgent": 12, "this week": 10,
    "deadline": 8, "time sensitive": 8, "critical": 8,
}

SALARY_PAT = re.compile(r"[$€£]\s?\d{1,3}[k]?\s?[-–]\s?[$€£]?\s?\d{1,3}[k]?", re.IGNORECASE)
COMPANY_PAT = re.compile(r"at\s+([A-Z][A-Za-z0-9\s&]+)\s*(?:we|'re|are|is|looking|hiring)", re.IGNORECASE)


class HeuristicProvider(LLMProvider):
    """Rule-based extraction — zero API cost, instant results."""

    async def analyze(self, raw_text: str, *, source: str = "", url: str = "") -> dict[str, Any]:
        text_lower = raw_text.lower()
        score = 20  # baseline

        # Score keyword matches
        for kw, w in HIRING_KEYWORDS.items():
            if kw in text_lower:
                score += w
        for kw, w in CLAUDE_KEYWORDS.items():
            if f" {kw} " in f" {text_lower} ":
                score += w
        for kw, w in PAIN_KEYWORDS.items():
            if kw in text_lower:
                score += w
        for kw, w in NEGATIVE_SIGNALS.items():
            if kw in text_lower:
                score += w
        for kw, w in URGENCY_PATTERNS.items():
            if kw in text_lower:
                score += w

        # Intent classification
        is_hiring = score > 60 or any(kw in text_lower for kw in ["hiring", "join us", "open role", "we're hiring"])
        is_evaluating = any(kw in text_lower for kw in ["looking for", "recommend", "alternatives to", "what do you use"])
        is_pain = any(kw in text_lower for kw in PAIN_KEYWORDS)

        if is_hiring:
            intent = "hiring"
        elif is_evaluating:
            intent = "evaluate"
        elif is_pain:
            intent = "pain"
        else:
            intent = "discover"

        # Band classification
        if score >= 85:
            band = "hot"
        elif score >= 65:
            band = "warm"
        elif score >= 40:
            band = "cool"
        else:
            band = "cold"

        # Company name extraction
        company_match = COMPANY_PAT.search(raw_text[:500])
        company = company_match.group(1).strip() if company_match else None

        # Salary range extraction
        salary = SALARY_PAT.search(raw_text)
        salary_str = salary.group(0) if salary else None

        # Best pain sentence
        sentences = raw_text.split(".")
        keywords = list(PAIN_KEYWORDS) + list(HIRING_KEYWORDS)[:5]
        pain = max(sentences, key=lambda s: sum(kw in s.lower() for kw in keywords))
        if len(pain) > 200:
            pain = pain[:200] + "..."

        return {
            "company_name": company or "Unknown",
            "contact_name": "Unknown",
            "contact_title": "Engineering" if is_hiring else "",
            "intent": intent,
            "urgency": "high" if any(kw in text_lower for kw in ["asap", "immediately", "urgent"]) else "medium",
            "confidence": min(max(score / 100.0, 0.0), 1.0),
            "opportunity_score": min(score, 100),
            "pain_point": pain.strip() or "",
            "raw_excerpt": (raw_text[:250] + "..." if len(raw_text) > 250 else raw_text),
            "source_url": url,
            "industry": "AI / Developer Tools" if any(kw in text_lower for kw in ["claude", "ai", "llm"]) else "General",
            "score_band": band,
            "final_score": min(score, 100),
            "salary_range": salary_str,
            "author": "Unknown",
        }

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        """No-op for heuristic provider."""
        return [[0.0] * 768 for _ in texts]
