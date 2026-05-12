"""
backend/llm/fallback_chain.py — 4-Tier LLM Fallback Chain
Inspired by WorldMonitor's architecture. Steps down through tiers gracefully.
Tier 1: Ollama (local, zero cost, offline)
Tier 2: Groq (cloud, fast, free tier 500 req/min)
Tier 3: OpenRouter (multi-model, generous free tier)
Tier 4: Browser T5 via Transformers.js (no server needed)
"""
from __future__ import annotations

import logging
import os
import json

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

TIER_TIMEOUT = 8.0  # seconds per tier


class FallbackChain:
    """Graceful LLM degradation across 4 tiers."""

    @staticmethod
    def _intent_prompt(text: str) -> str:
        return f"""Classify this lead signal into intent dimensions (0-100 each).
Return ONLY JSON with these keys: pain_explicit, hiring_intent, tech_growth, budget_signals, user_growth, champion_risk, competitive_indicators, urgency, category_momentum, community_sentiment, decision_maker_present, funding_runway, engagement_depth.

Text: {text[:2000]}

JSON:"""

    async def classify(self, text: str) -> dict[str, int]:
        """Try each tier in sequence until one succeeds."""
        prompt = self._intent_prompt(text)

        # Tier 1: Ollama (local, fastest)
        result = await self._tier_ollama(prompt)
        if result:
            return result

        # Tier 2: Groq (cloud, fast)
        result = await self._tier_groq(prompt)
        if result:
            return result

        # Tier 3: OpenRouter (multi-model)
        result = await self._tier_openrouter(prompt)
        if result:
            return result

        # Tier 4: Heuristic fallback (no server)
        return await self._tier_heuristic(text)

    async def _tier_ollama(self, prompt: str) -> dict[str, int] | None:
        try:
            async with httpx.AsyncClient(timeout=TIER_TIMEOUT) as client:
                resp = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={"model": "phi3:mini", "prompt": prompt, "stream": False, "options": {"temperature": 0.1, "num_predict": 256}},
                )
                if resp.status_code == 200:
                    raw = resp.json().get("response", "")
                    return self._parse_json(raw)
        except Exception:
            pass
        return None

    async def _tier_groq(self, prompt: str) -> dict[str, int] | None:
        if not GROQ_API_KEY:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIER_TIMEOUT) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 256},
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    return self._parse_json(raw)
        except Exception:
            pass
        return None

    async def _tier_openrouter(self, prompt: str) -> dict[str, int] | None:
        if not OPENROUTER_API_KEY:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIER_TIMEOUT) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "HTTP-Referer": "https://leadiq.local"},
                    json={"model": "mistralai/mistral-7b-instruct:free", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 256},
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    return self._parse_json(raw)
        except Exception:
            pass
        return None

    async def _tier_heuristic(self, text: str) -> dict[str, int]:
        """Zero-dependency heuristic classification."""
        from backend.engine.intent_signals import EXTRACTORS
        dims = {}
        for name, extractor in EXTRACTORS.items():
            score, _ = extractor.score(text)
            dims[name] = score
        return dims

    @staticmethod
    def _parse_json(text: str) -> dict[str, int]:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "").strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {k: min(max(int(float(v)), 0), 100) for k, v in data.items() if isinstance(v, (int, float))}
        except (json.JSONDecodeError, ValueError):
            pass
        return None