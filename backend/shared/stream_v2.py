"""
shared/stream_v2.py — Enhanced multi-source Redis Stream module.

Extends stream.py with:
  - Multi-source routing (separate streams per platform tier)
  - Per-stream dead letter queues
  - Checkpoint tracking for replay
  - Backpressure monitoring
  - Metrics (publish lag, consumer lag, throughput)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import redis.asyncio as aioredis

from backend.shared.config import settings

# ── Tier Definitions ──────────────────────────────────────────────────────────

class StreamTier(StrEnum):
    """Platform tiers with separate streams for backpressure isolation."""
    TIER1_CRITICAL = "tier1"     # High-volume job platforms
    TIER2_STANDARD = "tier2"     # Standard job platforms
    TIER3_GOVERNMENT = "tier3"   # Government data sources
    TIER4_NICHE = "tier4"        # Niche / batch platforms
    TIER5_SOCIAL = "tier5"       # Social media sources

TIER_STREAMS: dict[StreamTier, str] = {
    StreamTier.TIER1_CRITICAL: "lead:collected:tier1",
    StreamTier.TIER2_STANDARD: "lead:collected:tier2",
    StreamTier.TIER3_GOVERNMENT: "lead:collected:tier3",
    StreamTier.TIER4_NICHE: "lead:collected:tier4",
    StreamTier.TIER5_SOCIAL: "lead:collected:tier5",
}

TIER_DLQ: dict[StreamTier, str] = {
    tier: f"{stream}:dlq" for tier, stream in TIER_STREAMS.items()
}

PLATFORM_TIER_MAP: dict[str, StreamTier] = {
    # Tier 1 — Critical job platforms
    "naukri": StreamTier.TIER1_CRITICAL,
    "internshala": StreamTier.TIER1_CRITICAL,
    "linkedin": StreamTier.TIER1_CRITICAL,
    "indeed": StreamTier.TIER1_CRITICAL,
    "shine": StreamTier.TIER1_CRITICAL,
    # Tier 2 — Standard job platforms
    "monster": StreamTier.TIER2_STANDARD,
    "naukrigulf": StreamTier.TIER2_STANDARD,
    "timesjobs": StreamTier.TIER2_STANDARD,
    "foundit": StreamTier.TIER2_STANDARD,
    "weekday": StreamTier.TIER2_STANDARD,
    # Tier 3 — Government
    "dpiit": StreamTier.TIER3_GOVERNMENT,
    "mca21": StreamTier.TIER3_GOVERNMENT,
    "gem": StreamTier.TIER3_GOVERNMENT,
    "msme": StreamTier.TIER3_GOVERNMENT,
    "apisetu": StreamTier.TIER3_GOVERNMENT,
    # Tier 4 — Niche
    "freshersworld": StreamTier.TIER4_NICHE,
    "hirist": StreamTier.TIER4_NICHE,
    "cutshort": StreamTier.TIER4_NICHE,
    "instahyre": StreamTier.TIER4_NICHE,
    "hirect": StreamTier.TIER4_NICHE,
    "sarkari_result": StreamTier.TIER4_NICHE,
    "freejobalert": StreamTier.TIER4_NICHE,
    "employment_news": StreamTier.TIER4_NICHE,
    "iimjobs": StreamTier.TIER4_NICHE,
    # Tier 5 — Social media
    "github": StreamTier.TIER5_SOCIAL,
    "reddit": StreamTier.TIER5_SOCIAL,
    "hn": StreamTier.TIER5_SOCIAL,
    "producthunt": StreamTier.TIER5_SOCIAL,
    "stackoverflow": StreamTier.TIER5_SOCIAL,
    "twitter": StreamTier.TIER5_SOCIAL,
    "telegram": StreamTier.TIER5_SOCIAL,
    "rss": StreamTier.TIER5_SOCIAL,
}


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class StreamMetrics:
    """Per-stream metrics snapshot."""
    stream: str
    tier: StreamTier
    current_length: int = 0
    consumer_lag: float = 0.0  # seconds
    publish_rate_1m: float = 0.0  # events per minute
    dlq_count: int = 0
    last_event_age_seconds: float = 0.0


@dataclass
class Checkpoint:
    """Consumer checkpoint for replay support."""
    consumer: str
    stream: str
    last_event_id: str
    processed_count: int = 0
    error_count: int = 0
    last_processed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ── Enhanced Stream Client ────────────────────────────────────────────────────

class RedisStreamClientV2:
    """Enhanced multi-source stream client with monitoring and DLQ."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._client: aioredis.Redis | None = None
        self._redis_url = redis_url or settings.REDIS_URL
        self._metrics_cache: dict[str, StreamMetrics] = {}
        self._checkpoints: dict[str, Checkpoint] = {}

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def _r(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("RedisStreamClientV2 not connected")
        return self._client

    # ── Source Routing ────────────────────────────────────────────────────────

    def get_tier(self, source: str) -> StreamTier:
        """Map a platform/source name to its stream tier."""
        return PLATFORM_TIER_MAP.get(source, StreamTier.TIER4_NICHE)

    def get_stream(self, source: str) -> str:
        """Get the stream name for a given source."""
        tier = self.get_tier(source)
        return TIER_STREAMS[tier]

    def get_dlq(self, source: str) -> str:
        """Get the DLQ stream name for a given source."""
        tier = self.get_tier(source)
        return TIER_DLQ[tier]

    # ── Publish with routing ──────────────────────────────────────────────────

    async def publish(self, source: str, data: dict[str, Any]) -> str:
        """Publish to the correct tiered stream based on source."""
        stream = self.get_stream(source)
        payload: dict[str, str] = {}
        for k, v in data.items():
            payload[k] = v if isinstance(v, str) else json.dumps(v, default=str)
        payload["_source"] = source
        payload["_tier"] = self.get_tier(source).value
        payload["_published_at"] = str(time.time())
        event_id = await self._r.xadd(stream, payload, maxlen=100_000)
        return event_id

    # ── Dead Letter Queue ─────────────────────────────────────────────────────

    async def send_to_dlq(
        self, source: str, original_event_id: str, data: dict[str, Any],
        reason: str, error: str = "",
    ) -> str:
        """Move a failed event to the per-source DLQ stream."""
        dlq_stream = self.get_dlq(source)
        payload = {
            "original_event_id": original_event_id,
            "original_data": json.dumps(data, default=str),
            "source": source,
            "failure_reason": reason,
            "error_message": error,
            "failed_at": str(time.time()),
        }
        dlq_id = await self._r.xadd(dlq_stream, payload, maxlen=10_000)
        return dlq_id

    async def get_dlq_count(self, source: str) -> int:
        """Get the current DLQ depth for a source."""
        dlq_stream = self.get_dlq(source)
        try:
            result = await self._r.xlen(dlq_stream)
            return result or 0
        except Exception:
            return 0

    async def replay_from_dlq(self, source: str, count: int = 10) -> list[dict[str, Any]]:
        """Read events from DLQ for replay. Returns decoded events."""
        dlq_stream = self.get_dlq(source)
        results = await self._r.xrevrange(dlq_stream, "+", "-", count=count)
        events = []
        for event_id, raw in results:
            decoded = {k: _try_json(v) for k, v in raw.items()}
            decoded["_dlq_event_id"] = event_id
            events.append(decoded)
        return events

    async def clear_dlq(self, source: str) -> int:
        """Delete all events from a source's DLQ stream."""
        dlq_stream = self.get_dlq(source)
        result = await self._r.xtrim(dlq_stream, 0)
        return result or 0

    # ── Checkpoints ───────────────────────────────────────────────────────────

    async def save_checkpoint(self, consumer: str, stream: str, event_id: str) -> None:
        """Save a consumer checkpoint for replay support."""
        key = f"checkpoint:{consumer}:{stream}"
        checkpoint = {
            "consumer": consumer,
            "stream": stream,
            "last_event_id": event_id,
            "timestamp": str(time.time()),
        }
        await self._r.hset(key, mapping=checkpoint)

    async def get_checkpoint(self, consumer: str, stream: str) -> str | None:
        """Get the last processed event ID for a consumer."""
        key = f"checkpoint:{consumer}:{stream}"
        result = await self._r.hget(key, "last_event_id")
        return result

    async def replay_from_checkpoint(
        self, consumer: str, stream: str, count: int = 100,
    ) -> list[dict[str, Any]]:
        """Replay events from the last checkpoint."""
        last_id = await self.get_checkpoint(consumer, stream)
        if not last_id:
            return []
        results = await self._r.xrange(stream, last_id, "+", count=count)
        events = []
        for event_id, raw in results:
            if event_id == last_id:
                continue
            decoded = {k: _try_json(v) for k, v in raw.items()}
            decoded["_event_id"] = event_id
            events.append(decoded)
        return events

    # ── Backpressure ──────────────────────────────────────────────────────────

    async def get_stream_length(self, source: str) -> int:
        """Get the current length of a source's stream."""
        stream = self.get_stream(source)
        try:
            result = await self._r.xlen(stream)
            return result or 0
        except Exception:
            return 0

    async def is_backpressured(self, source: str, threshold: int = 10_000) -> bool:
        """Check if a source's stream is backpressured (too many unprocessed events)."""
        length = await self.get_stream_length(source)
        return length >= threshold

    async def get_all_stream_lengths(self) -> dict[str, int]:
        """Get lengths of all tiered streams."""
        lengths = {}
        for stream in TIER_STREAMS.values():
            try:
                result = await self._r.xlen(stream)
                lengths[stream] = result or 0
            except Exception:
                lengths[stream] = -1
        return lengths

    # ── Metrics ───────────────────────────────────────────────────────────────

    async def get_stream_metrics(self, tier: StreamTier | None = None) -> list[StreamMetrics]:
        """Get metrics for one or all tiers."""
        streams_to_check = (
            [TIER_STREAMS[tier]] if tier else list(TIER_STREAMS.values())
        )
        metrics_list = []
        for stream in streams_to_check:
            try:
                length = await self._r.xlen(stream) or 0
            except Exception:
                length = -1

            tier_for_stream = next(
                (t for t, s in TIER_STREAMS.items() if s == stream),
                StreamTier.TIER4_NICHE,
            )

            metrics = StreamMetrics(
                stream=stream,
                tier=tier_for_stream,
                current_length=length,
            )

            # DLQ count
            dlq_stream = TIER_DLQ.get(tier_for_stream, "")
            if dlq_stream:
                try:
                    metrics.dlq_count = await self._r.xlen(dlq_stream) or 0
                except Exception:
                    pass

            metrics_list.append(metrics)

        return metrics_list


def _try_json(value: str) -> Any:
    """Try JSON decode; fall back to raw string."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


# Singleton
redis_stream_v2 = RedisStreamClientV2()
