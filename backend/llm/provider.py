"""
llm/provider.py — LLM Provider abstraction.

Switch between LLM backends via env var:
  LLM_PROVIDER=gemini  →  use Google Gemini
  LLM_PROVIDER=heuristic → use rule-based (no API key, zero cost)
  LLM_PROVIDER=ide     →  route through IDE model (Kimi/Claude)

Usage:
    from backend.llm.provider import get_provider
    provider = get_provider()
    lead = await provider.analyze(post)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract base for all LLM backends."""

    @abstractmethod
    async def analyze(self, raw_text: str, *, source: str = "", url: str = "") -> dict[str, Any]:
        """Analyze a raw post and return structured lead data."""
        ...

    @abstractmethod
    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for similarity search."""
        ...


def get_provider() -> LLMProvider:
    """Factory: returns the active LLM provider based on env."""
    provider = os.getenv("LLM_PROVIDER", "heuristic").lower()
    if provider == "gemini":
        from backend.llm.gemini_provider import GeminiProvider
        return GeminiProvider()
    if provider == "ide":
        from backend.llm.ide_provider import IDEProvider
        return IDEProvider()

    from backend.llm.heuristic_provider import HeuristicProvider
    return HeuristicProvider()
