"""
llm_router.py — Multi-LLM orchestration with connection pooling, caching,
multi-model routing, structured output, and parallel batch execution.

Primary: NVIDIA NIM (free tier) — DeepSeek R1, Llama 3.1 8B, Mixtral 8x7B
Secondary: Gemini Flash (GCP 3-month trial) — 60 RPM
Fallback: Kimi K2.6 (OpenCode)

Optimizations:
  1. Connection pooling — shared aiohttp session across all calls
  2. Redis response cache — TTL-based dedup for identical prompts
  3. Multi-model routing — Llama 8B for fast tasks, Mixtral for medium,
     DeepSeek R1 only for complex reasoning
  4. Structured output — NVIDIA JSON mode via response_format
  5. Parallel batch — concurrent multi-prompt execution
  6. Prompt compression — automatic truncation of long prefix text
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp
from backend.shared.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    text: str
    model: str
    latency_ms: int
    cost_usd: float
    tokens_used: int
    success: bool
    error: Optional[str] = None
    cached: bool = False


# ── Connection Pool Manager ────────────────────────────────────────────────
# Optimization 1: Shared aiohttp session across all LLM calls

class SessionPool:
    """Manages a single persistent aiohttp session for all LLM providers."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

    async def get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(
                limit=10,
                limit_per_host=5,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        if self._connector:
            await self._connector.close()


_session_pool = SessionPool()


# ── Redis Cache ─────────────────────────────────────────────────────────────
# Optimization 2: TTL-based cache for identical prompts

class LLMCache:
    """Redis-backed LLM response cache with TTL."""

    CACHE_TTL = {
        "extraction": 3600,
        "analysis": 600,
        "generation": 300,
        "default": 900,
    }

    def __init__(self):
        self._redis = None
        self._local: Dict[str, tuple[float, str]] = {}

    async def _get_redis(self):
        if self._redis is None:
            try:
                from backend.shared.stream import redis_stream
                # Redis is already available via the stream client
                url = settings.REDIS_URL
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(url, decode_responses=True)
            except Exception:
                self._redis = False
        return self._redis if self._redis else None

    def _make_key(self, prompt: str, model: str, temperature: float) -> str:
        h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return f"llm:cache:{model}:{h}:{int(temperature * 10)}"

    async def get(self, prompt: str, model: str, temperature: float) -> Optional[str]:
        # L1: local dict cache
        key = self._make_key(prompt, model, temperature)
        hit = self._local.get(key)
        if hit:
            ts, val = hit
            if time.time() - ts < 60:
                return val

        # L2: Redis cache
        redis = await self._get_redis()
        if redis:
            try:
                val = await redis.get(key)
                if val:
                    self._local[key] = (time.time(), val)
                    return val
            except Exception:
                pass
        return None

    async def set(self, prompt: str, model: str, temperature: float, value: str, task_type: str = "default"):
        key = self._make_key(prompt, model, temperature)
        self._local[key] = (time.time(), value)
        ttl = self.CACHE_TTL.get(task_type, 900)
        redis = await self._get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, value)
            except Exception:
                pass

    async def clear(self):
        self._local.clear()
        redis = await self._get_redis()
        if redis:
            try:
                await redis.flushdb()
            except Exception:
                pass


_cache = LLMCache()


# ── Prompt Compression ──────────────────────────────────────────────────────
# Optimization 6: Automatic truncation of long prefix text

def compress_prompt(prompt: str, max_chars: int = 4000) -> str:
    """Compress prompt by truncating middle sections if too long."""
    if len(prompt) <= max_chars:
        return prompt

    # Keep first 60% and last 30%, remove middle
    head_len = int(max_chars * 0.6)
    tail_len = int(max_chars * 0.3)
    head = prompt[:head_len]
    tail = prompt[-tail_len:]
    return head + "\n...[content truncated for length]...\n" + tail


# ── Abstract Provider ──────────────────────────────────────────────────────

class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        json_mode: bool = False,
    ) -> LLMResponse:
        ...


NVIDIA_MODELS = {
    "nemotron-3-super-120b": "nvidia/nemotron-3-super-120b-a12b",
    "nemotron-3-nano-omni": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nemotron-nano-9b-v2": "nvidia/nvidia-nemotron-nano-9b-v2",
    "mistral-nemotron": "mistralai/mistral-nemotron",
    "llama-3.1-8b": "meta/llama-3.1-8b-instruct",
    "mixtral-8x7b": "mistralai/mixtral-8x7b-instruct-v0.1",
    "deepseek-r1": "deepseek-ai/deepseek-r1",
}

DEFAULT_FAST_MODEL = "nemotron-nano-9b-v2"
DEFAULT_MEDIUM_MODEL = "mistral-nemotron"
DEFAULT_REASONING_MODEL = "nemotron-3-super-120b"

OPENROUTER_MODELS = {
    "kimi-k2.6": "mistralai/mistral-7b-instruct:free",
    "kimi-k2.5": "mistralai/mixtral-8x7b-instruct:free",
    "claude-sonnet-4": "anthropic/claude-sonnet-4",
    "claude-haiku-3.5": "anthropic/claude-3.5-haiku",
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gemini-2.0-flash": "google/gemini-2.0-flash-001",
}

ALL_MODELS = {**NVIDIA_MODELS, **OPENROUTER_MODELS}

MODEL_CATEGORIES = {
    "nvidia": list(NVIDIA_MODELS.keys()),
    "openrouter": list(OPENROUTER_MODELS.keys()),
}

TASK_TO_MODEL = {
    "fast": DEFAULT_FAST_MODEL,
    "medium": DEFAULT_MEDIUM_MODEL,
    "reasoning": DEFAULT_REASONING_MODEL,
}


class NVIDIAProvider(LLMProvider):
    """
    NVIDIA NIM API with multi-model routing.

    Primary models (user-provided NVIDIA API key):
    - nemotron-3-super-120b: Large hybrid Mamba-Transformer, complex reasoning/planning
    - nemotron-3-nano-omni: Omni-modal (text/images/video/speech), 30B
    - nemotron-nano-9b-v2: Agentic tasks, high efficiency
    - mistral-nemotron: Mistral AI collaboration model

    Fallback models (free tier):
    - llama-3.1-8b: Fast extraction/classification
    - mixtral-8x7b: Medium analysis/scoring
    - deepseek-r1: Complex reasoning
    """

    MODEL_ALIASES = dict(NVIDIA_MODELS)

    def __init__(self, model_name: str = DEFAULT_FAST_MODEL):
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = "https://integrate.api.nvidia.com/v1"
        self.model_name = model_name
        self.model = self.MODEL_ALIASES.get(model_name, model_name)

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        json_mode: bool = False,
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="", model="nvidia", latency_ms=0, cost_usd=0,
                tokens_used=0, success=False, error="NVIDIA_API_KEY not set"
            )

        start = time.time()
        try:
            session = await _session_pool.get()
            prompt = compress_prompt(prompt)
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            async with session.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as resp:
                data = await resp.json()
                latency = int((time.time() - start) * 1000)

                if resp.status != 200:
                    return LLMResponse(
                        text="", model=f"nvidia:{self.model_name}", latency_ms=latency,
                        cost_usd=0, tokens_used=0, success=False,
                        error=f"HTTP {resp.status}: {data.get('error', {}).get('message', 'Unknown')}"
                    )

                text = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)

                return LLMResponse(
                    text=text, model=f"nvidia:{self.model_name}:{self.model.split('/')[-1]}",
                    latency_ms=latency, cost_usd=0,
                    tokens_used=tokens, success=True,
                )
        except asyncio.TimeoutError:
            return LLMResponse(
                text="", model=f"nvidia:{self.model_name}", latency_ms=int((time.time() - start) * 1000),
                cost_usd=0, tokens_used=0, success=False, error="Timeout"
            )
        except Exception as exc:
            return LLMResponse(
                text="", model=f"nvidia:{self.model_name}", latency_ms=int((time.time() - start) * 1000),
                cost_usd=0, tokens_used=0, success=False, error=str(exc),
            )


class GeminiProvider(LLMProvider):
    """Gemini Flash via GCP — high volume, low cost."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.model = "gemini-3-flash-preview-0514"

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        json_mode: bool = False,
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="", model="gemini", latency_ms=0, cost_usd=0,
                tokens_used=0, success=False, error="GEMINI_API_KEY not set"
            )

        start = time.time()
        try:
            session = await _session_pool.get()
            url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
            prompt = compress_prompt(prompt)

            payload: Dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            }
            if json_mode:
                payload["generationConfig"]["response_mime_type"] = "application/json"

            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                latency = int((time.time() - start) * 1000)

                if resp.status != 200:
                    return LLMResponse(
                        text="", model="gemini", latency_ms=latency,
                        cost_usd=0, tokens_used=0, success=False,
                        error=f"HTTP {resp.status}: {data.get('error', {}).get('message', 'Unknown')}"
                    )

                text = data["candidates"][0]["content"]["parts"][0]["text"]
                tokens = len(prompt.split()) + len(text.split())

                return LLMResponse(
                    text=text, model="gemini:flash",
                    latency_ms=latency, cost_usd=0,
                    tokens_used=tokens, success=True,
                )
        except Exception as exc:
            return LLMResponse(
                text="", model="gemini", latency_ms=int((time.time() - start) * 1000),
                cost_usd=0, tokens_used=0, success=False, error=str(exc),
            )


class KimiProvider(LLMProvider):
    """Kimi K2.6 fallback — requires active OpenCode session."""

    def __init__(self):
        self.model = "kimi-k2.6:cloud"

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        json_mode: bool = False,
    ) -> LLMResponse:
        return LLMResponse(
            text="[Kimi K2.6 fallback — requires OpenCode session]",
            model="kimi", latency_ms=0, cost_usd=0,
            tokens_used=0, success=False,
            error="Kimi K2.6 requires active OpenCode session"
        )


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider — Kimi, Claude, GPT, and 100+ models."""

    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.base_url = "https://openrouter.ai/api/v1"
        self.model = OPENROUTER_MODELS.get("kimi-k2.6", "mistralai/mistral-7b-instruct:free")

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        json_mode: bool = False,
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="", model="openrouter", latency_ms=0, cost_usd=0,
                tokens_used=0, success=False, error="OPENROUTER_API_KEY not set"
            )

        start = time.time()
        try:
            session = await _session_pool.get()
            prompt = compress_prompt(prompt)
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            async with session.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "https://leadiq.local",
                },
                json=payload,
            ) as resp:
                data = await resp.json()
                latency = int((time.time() - start) * 1000)

                if resp.status != 200:
                    return LLMResponse(
                        text="", model="openrouter", latency_ms=latency,
                        cost_usd=0, tokens_used=0, success=False,
                        error=f"HTTP {resp.status}: {data.get('error', {}).get('message', 'Unknown')}"
                    )

                text = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                model_used = data.get("model", "unknown")

                return LLMResponse(
                    text=text, model=f"openrouter:{model_used}",
                    latency_ms=latency,
                    cost_usd=float(data.get("usage", {}).get("total_cost", 0) or 0),
                    tokens_used=tokens, success=True,
                )
        except Exception as exc:
            return LLMResponse(
                text="", model="openrouter", latency_ms=int((time.time() - start) * 1000),
                cost_usd=0, tokens_used=0, success=False, error=str(exc),
            )


class LLMRouter:
    """
    Multi-LLM router with automatic model selection, caching, and fallback.

    Model selection by task:
      extraction/generation → Llama 3.1 8B (fast, ~200ms)
      analysis/classification → Mixtral 8x7B (medium, ~500ms)
      reasoning/coding → DeepSeek R1 (slow, ~2s)
    """

    # Optimization 3: Multi-model routing
    TASK_TIER_MAP: Dict[str, str] = {
        "extraction": "fast",
        "generation": "fast",
        "classification": "fast",
        "analysis": "medium",
        "scoring": "medium",
        "reasoning": "reasoning",
        "coding": "reasoning",
        "planning": "reasoning",
        "default": "fast",
    }

    AVAILABLE_PROVIDERS = ["nvidia", "openrouter", "gemini", "kimi"]

    def __init__(self, model_preference: Optional[str] = None):
        self.providers: Dict[str, LLMProvider] = {}
        self.cache = _cache
        self.default_model = model_preference or DEFAULT_FAST_MODEL

    def _resolve_nvidia_model(self, model_name: str) -> str:
        """Resolve model alias to full NVIDIA model name."""
        if model_name in NVIDIA_MODELS:
            return NVIDIA_MODELS[model_name]
        return model_name  # Pass through as-is (full path)

    def _get_provider(self, model_name: str) -> NVIDIAProvider:
        if model_name not in self.providers:
            self.providers[model_name] = NVIDIAProvider(model_name=model_name)
        return self.providers[model_name]

    async def generate(
        self,
        prompt: str,
        task_type: str = "default",
        model_preference: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        use_cache: bool = True,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Generate text with automatic model selection, caching, and fallback.

        Args:
            prompt: Input prompt
            task_type: extraction|generation|classification|analysis|scoring|reasoning|coding|planning
            model_preference: Override automatic model.
                NVIDIA: nemotron-3-super-120b, nemotron-3-nano-omni, nemotron-nano-9b-v2, mistral-nemotron,
                        llama-3.1-8b, mixtral-8x7b, deepseek-r1
                OpenRouter: kimi-k2.6, kimi-k2.5, claude-sonnet-4, claude-haiku-3.5, gpt-4o-mini, gemini-2.0-flash
                Direct: gemini
            temperature: Sampling temperature
            max_tokens: Max output tokens
            use_cache: Enable response caching
            json_mode: Request structured JSON output

        Returns:
            LLMResponse with text, model, latency, cost
        """
        prompt = prompt.strip()
        if not prompt:
            return LLMResponse(
                text="", model="none", latency_ms=0, cost_usd=0,
                tokens_used=0, success=False, error="Empty prompt"
            )

        # Check cache (Optimization 2)
        if use_cache:
            cache_key_model = model_preference or TASK_TO_MODEL.get(task_type, DEFAULT_FAST_MODEL)
            cached = await self.cache.get(prompt, cache_key_model, temperature)
            if cached is not None:
                return LLMResponse(
                    text=cached, model=f"cache:{cache_key_model}",
                    latency_ms=0, cost_usd=0, tokens_used=0,
                    success=True, cached=True,
                )

        # Determine fallback order
        fallback_order: List[str] = []

        if model_preference:
            if model_preference in NVIDIA_MODELS:
                fallback_order = [f"nvidia:{model_preference}", "gemini"]
            elif model_preference in OPENROUTER_MODELS:
                fallback_order = [f"openrouter:{model_preference}", "gemini"]
            elif model_preference == "gemini":
                fallback_order = ["gemini"]
            else:
                fallback_order = [f"nvidia:{DEFAULT_FAST_MODEL}", "gemini"]
        else:
            tier = self.TASK_TIER_MAP.get(task_type, "fast")
            model_name = TASK_TO_MODEL.get(tier, DEFAULT_FAST_MODEL)
            fallback_order = [f"nvidia:{model_name}", "gemini"]

        # Try each provider
        for model_key in fallback_order:
            if model_key.startswith("nvidia:"):
                model_name = model_key.split(":", 1)[1]
                provider = self._get_provider(model_name)
                provider_key = model_name
            elif model_key.startswith("openrouter:"):
                model_name = model_key.split(":", 1)[1]
                provider_key = f"openrouter:{model_name}"
                if "openrouter" not in self.providers:
                    self.providers["openrouter"] = OpenRouterProvider()
                provider = self.providers["openrouter"]
            elif model_key == "gemini":
                provider_key = "gemini"
                if "gemini" not in self.providers:
                    self.providers["gemini"] = GeminiProvider()
                provider = self.providers["gemini"]
            else:
                continue

            result = await provider.generate(prompt, temperature, max_tokens, json_mode)
            if result.success:
                if use_cache and not result.cached:
                    await self.cache.set(prompt, provider_key, temperature, result.text, task_type)
                return result
            logger.warning(f"LLM failed: {model_key}, error: {result.error}")

        return LLMResponse(
            text="", model="all_failed", latency_ms=0,
            cost_usd=0, tokens_used=0, success=False,
            error="All LLM providers failed",
        )

    # Optimization 5: Parallel batch execution
    async def batch_generate(
        self,
        prompts: List[tuple[str, str, float, int, bool]],
        task_type: str = "default",
        max_concurrent: int = 5,
    ) -> List[LLMResponse]:
        """
        Execute multiple prompts in parallel.

        Args:
            prompts: List of (prompt, task_type_override, temperature, max_tokens, json_mode)
            task_type: Default task type
            max_concurrent: Max concurrent LLM calls

        Returns:
            List of LLMResponse in same order
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _limited(p: tuple[str, str, float, int, bool]) -> LLMResponse:
            prompt, tt, temp, mt, jm = p
            async with sem:
                return await self.generate(
                    prompt=prompt,
                    task_type=tt or task_type,
                    temperature=temp,
                    max_tokens=mt,
                    json_mode=jm,
                )

        tasks = [_limited(p) for p in prompts]
        return await asyncio.gather(*tasks)

    async def close(self):
        await _session_pool.close()


# ── Singleton ──────────────────────────────────────────────────────────────

_router = None


def get_llm_router(model_preference: Optional[str] = None) -> LLMRouter:
    """Get singleton LLM router."""
    global _router
    if _router is None:
        _router = LLMRouter(model_preference=model_preference)
    return _router
