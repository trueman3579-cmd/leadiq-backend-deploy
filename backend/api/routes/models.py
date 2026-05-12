"""
api/routes/models.py — LLM Models API.

Lists available models from NVIDIA, OpenRouter, and Gemini.
Dynamically fetches NVIDIA model catalog via API.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter
import httpx

from backend.services.llm_router import NVIDIA_MODELS, OPENROUTER_MODELS
from backend.shared.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/models", tags=["models"])

EXCLUDE_PATTERNS = [
    "embed", "safety", "content-safety", "guard", "reward",
    "fuyu", "bge", "starcoder", "dbrx", "yi-large",
]

NVIDIA_CHAT_CATEGORIES = {
    "nemotron": "Nemotron Series",
    "llama": "Llama Series",
    "mistral": "Mistral Series",
    "mixtral": "Mixtral Series",
    "deepseek": "DeepSeek Series",
    "qwen": "Qwen Series",
    "gemma": "Gemma Series",
    "phi": "Phi Series",
    "command": "Command Series",
    "claude": "Claude Series",
    "gpt": "GPT Series",
}


@router.get("")
async def list_models():
    """List all available LLM models grouped by provider."""
    nvidia_dynamic = await _fetch_nvidia_models()
    return {
        "nvidia": {
            "curated": dict(NVIDIA_MODELS),
            "all": nvidia_dynamic,
        },
        "openrouter": dict(OPENROUTER_MODELS),
        "default": {
            "fast": "nemotron-nano-9b-v2",
            "medium": "mistral-nemotron",
            "reasoning": "nemotron-3-super-120b",
        },
        "total_nvidia": len(nvidia_dynamic),
    }


async def _fetch_nvidia_models() -> dict[str, list[str]]:
    """Dynamically fetch NVIDIA model catalog and group by category."""
    if not settings.NVIDIA_API_KEY:
        return {}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://integrate.api.nvidia.com/v1/models",
                headers={"Authorization": f"Bearer {settings.NVIDIA_API_KEY}"},
            )
            if resp.status_code != 200:
                return {}

            data = resp.json()
            models = data.get("data", [])
            grouped: dict[str, list[str]] = {}

            for m in models:
                mid = m["id"]
                if any(p in mid.lower() for p in EXCLUDE_PATTERNS):
                    continue
                if "instruct" not in mid.lower() and "chat" not in mid.lower() and "nemotron" not in mid.lower() and "r1" not in mid.lower() and "qwen" not in mid.lower() and "mistral" not in mid.lower() and "llama" not in mid.lower():
                    continue

                cat = "other"
                for key, label in NVIDIA_CHAT_CATEGORIES.items():
                    if key in mid.lower():
                        cat = label
                        break
                if cat not in grouped:
                    grouped[cat] = []
                grouped[cat].append(mid)

            # Sort each category
            for cat in grouped:
                grouped[cat].sort()
            return dict(sorted(grouped.items()))

    except Exception as e:
        logger.warning("nvidia_model_fetch_failed", error=str(e))
        return {}
