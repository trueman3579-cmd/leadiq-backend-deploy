"""
backend/llm/ollama_provider.py — Local + Cloud Ollama Provider
Uses tiny models (3B params) for real-time inference. Zero-cost if self-hosted,
or ultra-cheap via Ollama Cloud (~$0.0001 per request).
"""
from __future__ import annotations

import json
import logging

import httpx
from backend.shared.config import settings

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
DEFAULT_MODEL = settings.OLLAMA_MODEL  # 3.8B params, ~2GB RAM
CLOUD_FALLBACK = settings.OLLAMA_CLOUD_URL  # e.g. "https://api.ollama.cloud/v1"

# Lightweight models ranked by speed/quality tradeoff
LIGHTWEIGHT_MODELS = {
    "phi3:mini": {"params": "3.8B", "ram_gb": 2, "quality": 75, "speed": 95},
    "llama3.2:1b": {"params": "1B", "ram_gb": 1.5, "quality": 70, "speed": 98},
    "gemma2:2b": {"params": "2B", "ram_gb": 1.8, "quality": 72, "speed": 93},
    "qwen2.5:3b": {"params": "3B", "ram_gb": 2.2, "quality": 78, "speed": 92},
    "mistral:7b": {"params": "7B", "ram_gb": 5, "quality": 85, "speed": 80},
}

INTENT_PROMPT = """You are a world-class B2B intent detection engine. Analyze the following post and output ONLY a JSON object with scores 0-100 for each intent dimension.

Input Post:
---
{title}
{body}
---

Output JSON format (scores 0-100):
{{
  "pain_explicit": <int>,
  "hiring_intent": <int>,
  "tech_growth": <int>,
  "budget_signals": <int>,
  "user_growth": <int>,
  "champion_risk": <int>,
  "competitive_indicators": <int>,
  "urgency": <int>,
  "category_momentum": <int>,
  "community_sentiment": <int>,
  "decision_maker_present": <int>,
  "funding_runway": <int>,
  "engagement_depth": <int>
}}

Rules:
- pain_explicit: Are they expressing frustration, issues, or problems?
- hiring_intent: Are they hiring, recruiting, or growing team?
- tech_growth: Are they migrating, adopting, or evaluating new tech?
- budget_signals: Are they discussing money, budget, pricing, or ROI?
- user_growth: Are they scaling, experiencing traffic growth, or MAU increases?
- champion_risk: Are key people leaving or roles changing?
- competitive_indicators: Are they comparing, switching, or evaluating alternatives?
- urgency: Are there deadlines, ASAP, or time-sensitive language?
- category_momentum: Is this part of a broader trend?
- community_sentiment: Is the sentiment positive/negative about a solution?
- decision_maker_present: Are executives (CTO, VP, Director) mentioned?
- funding_runway: Are they discussing funding, Series, burn rate?
- engagement_depth: Are they deep in evaluation, pilot, POC?

Output ONLY valid JSON. No markdown, no explanation."""


class OllamaProvider:
    """Lightweight Ollama provider using 1-3B parameter models."""

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = OLLAMA_BASE_URL) -> None:
        self.model = model
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def classify_intent(self, title: str, body: str) -> dict[str, int]:
        """Run LLM classification on a post. Returns dimension scores."""
        prompt = INTENT_PROMPT.format(title=title, body=body[:2000])  # Truncate for speed

        try:
            response = await self._client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 512},
                },
            )
            response.raise_for_status()
            data = response.json()
            raw_output = data.get("response", "{}")

            # Extract JSON from possible markdown
            clean = raw_output.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1].replace("json", "").strip()

            result = json.loads(clean)
            return {k: min(max(int(v), 0), 100) for k, v in result.items() if isinstance(v, (int, float))}

        except json.JSONDecodeError as e:
            logger.warning("Ollama returned invalid JSON: %s", e)
            return {}
        except Exception as e:
            logger.error("Ollama classification failed: %s", e)
            return {}

    async def close(self) -> None:
        await self._client.aclose()
