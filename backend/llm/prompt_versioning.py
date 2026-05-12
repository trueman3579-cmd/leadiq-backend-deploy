"""
prompt_versioning.py — Prompt Version Registry + A/B Experiment Framework (Day 18)

Tracks prompt versions per source. Enables A/B testing of prompt variants with
Redis-backed metrics to measure which variant produces better extraction quality.

Usage:
    from backend.llm.prompt_versioning import get_prompt_version, record_ab_result
    from backend.llm.prompt_versioning import start_experiment, get_experiment_assignment
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, UTC
from typing import Any

import redis.asyncio as aioredis

from backend.shared.config import settings

logger = logging.getLogger(__name__)

# ── Prompt Version Registry ──────────────────────────────────────────────────

PROMPT_VERSIONS: dict[str, str] = {
    "tracxn": "1.0.0",
    "indimart": "1.0.0",
    "github_profile": "1.0.0",
    "yourstory": "1.0.0",
    "producthunt": "1.0.0",
    "hacker_news": "1.0.0",
    "dpiit": "1.0.0",
    "mca21": "1.0.0",
}

PROMPT_CHANGELOG: dict[str, list[dict[str, str]]] = {
    "tracxn": [
        {"version": "1.0.0", "date": "2026-05-01", "author": "system",
         "change": "Initial prompt with Tracxn source grounding."},
    ],
    "indimart": [
        {"version": "1.0.0", "date": "2026-05-01", "author": "system",
         "change": "Initial IndiaMART supplier listing prompt."},
    ],
    "github_profile": [
        {"version": "1.0.0", "date": "2026-05-01", "author": "system",
         "change": "Initial GitHub profile extraction prompt."},
    ],
    "producthunt": [
        {"version": "1.0.0", "date": "2026-05-01", "author": "system",
         "change": "Initial Product Hunt launch extraction prompt."},
    ],
    "hacker_news": [
        {"version": "1.0.0", "date": "2026-05-01", "author": "system",
         "change": "Initial HN post extraction prompt."},
    ],
}

PROMPT_HASHES: dict[str, str] = {}  # Lazily computed


def get_prompt_version(source: str) -> str:
    """Returns the current version string for a source prompt."""
    return PROMPT_VERSIONS.get(source, "0.0.0-unknown")


def get_prompt_hash(prompt_text: str) -> str:
    """SHA256 hash of prompt text for fast equality checking."""
    return hashlib.sha256(prompt_text.encode()).hexdigest()[:16]


def bump_prompt_version(source: str, change: str, author: str = "system") -> str:
    """Bumps the patch version for a source prompt and records changelog."""
    current = PROMPT_VERSIONS.get(source, "0.0.0")
    parts = current.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    new_version = ".".join(parts)
    PROMPT_VERSIONS[source] = new_version

    if source not in PROMPT_CHANGELOG:
        PROMPT_CHANGELOG[source] = []

    PROMPT_CHANGELOG[source].append({
        "version": new_version,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "author": author,
        "change": change,
    })

    logger.info("prompt_version_bumped", source=source, version=new_version, change=change)
    return new_version


def get_changelog(source: str) -> list[dict[str, str]]:
    """Returns full changelog for a source prompt."""
    return PROMPT_CHANGELOG.get(source, [])


# ── A/B Experiment Framework ─────────────────────────────────────────────────

_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


async def start_experiment(
    experiment_name: str,
    variants: list[str],
    traffic_split: list[float] | None = None,
) -> dict[str, Any]:
    """
    Start an A/B experiment for prompt variants.

    variants: ["prompt_v1_hash", "prompt_v2_hash"]
    traffic_split: [0.5, 0.5] (must sum to 1.0)
    """
    if traffic_split is None:
        traffic_split = [1.0 / len(variants)] * len(variants)

    if abs(sum(traffic_split) - 1.0) > 0.01:
        return {"error": "Traffic split must sum to 1.0"}

    if len(variants) != len(traffic_split):
        return {"error": "variants and traffic_split must have same length"}

    r = await _get_redis()
    experiment_id = str(uuid.uuid4())[:8]
    key = f"ab_experiment:{experiment_id}"

    experiment = {
        "name": experiment_name,
        "variants": json.dumps(variants),
        "traffic_split": json.dumps(traffic_split),
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
    }
    await r.hset(key, mapping=experiment)
    await r.expire(key, 86400 * 30)  # 30 day TTL

    logger.info("ab_experiment_started", id=experiment_id, name=experiment_name,
                 variants=len(variants))

    return {
        "experiment_id": experiment_id,
        "name": experiment_name,
        "variants": variants,
        "traffic_split": traffic_split,
    }


async def get_experiment_assignment(
    experiment_id: str,
    lead_id: str,
) -> dict[str, Any]:
    """
    Deterministically assign a lead to a variant. Same lead always gets same variant.
    Returns {"variant": "prompt_v1_hash", "variant_index": 0}
    """
    r = await _get_redis()
    key = f"ab_experiment:{experiment_id}"
    data = await r.hgetall(key)

    if not data:
        return {"variant": None, "error": "Experiment not found"}

    if data.get("status") != "running":
        return {"variant": None, "error": f"Experiment status: {data.get('status')}"}

    variants = json.loads(data["variants"])
    traffic_split = json.loads(data["traffic_split"])

    # Deterministic assignment via hash
    hash_val = int(hashlib.md5(f"{experiment_id}:{lead_id}".encode()).hexdigest(), 16)
    bucket = (hash_val % 100) / 100.0

    cumulative = 0.0
    assigned_index = 0
    for i, split in enumerate(traffic_split):
        cumulative += split
        if bucket <= cumulative:
            assigned_index = i
            break

    await r.hincrby(key, f"assignments:{assigned_index}", 1)

    return {
        "variant": variants[assigned_index],
        "variant_index": assigned_index,
        "experiment_id": experiment_id,
    }


async def record_ab_result(
    experiment_id: str,
    variant_index: int,
    field_precision: float,
    tokens_used: int = 0,
) -> None:
    """Record extraction quality for a variant."""
    r = await _get_redis()
    key = f"ab_experiment:{experiment_id}"

    await r.hincrbyfloat(key, f"precision_sum:{variant_index}", field_precision)
    await r.hincrby(key, f"count:{variant_index}", 1)
    await r.hincrby(key, f"tokens:{variant_index}", tokens_used)

    logger.debug("ab_result_recorded", experiment=experiment_id,
                 variant=variant_index, precision=field_precision)


async def get_ab_results(experiment_id: str) -> dict[str, Any]:
    """Returns current A/B experiment results."""
    r = await _get_redis()
    key = f"ab_experiment:{experiment_id}"
    data = await r.hgetall(key)

    if not data:
        return {"error": "Experiment not found"}

    variants = json.loads(data["variants"])
    results = []
    for i, variant in enumerate(variants):
        count = int(data.get(f"count:{i}", 0))
        precision_sum = float(data.get(f"precision_sum:{i}", 0))
        tokens = int(data.get(f"tokens:{i}", 0))
        avg_precision = round(precision_sum / count, 4) if count > 0 else None

        results.append({
            "variant": variant,
            "index": i,
            "count": count,
            "avg_precision": avg_precision,
            "tokens_used": tokens,
        })

    # Determine winner
    best = max(results, key=lambda r: r["avg_precision"] or 0)

    return {
        "experiment_id": experiment_id,
        "name": data.get("name"),
        "status": data.get("status"),
        "started_at": data.get("started_at"),
        "variants": results,
        "leading_variant": best["variant"] if best["count"] > 0 else None,
    }


async def stop_experiment(experiment_id: str) -> dict[str, Any]:
    """Stop an experiment and return final results."""
    results = await get_ab_results(experiment_id)
    r = await _get_redis()
    key = f"ab_experiment:{experiment_id}"
    await r.hset(key, "status", "stopped")
    await r.hset(key, "stopped_at", datetime.now(UTC).isoformat())
    return {**results, "status": "stopped"}
