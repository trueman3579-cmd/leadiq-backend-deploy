"""
shared/stream.py — Redis Streams event bus wrapper.
RedisStreamClient: publish / consume / consume_group
StreamEvent: typed dataclass for all inter-worker events

Stream topology:
  lead:collected  → analyzer worker
  lead:analyzed   → scorer worker
  lead:scored     → ranker worker
  lead:ranked     → outreach worker / telegram notifier
  lead:outreach   → crm_update worker
  lead:crm_update → DB persistence
  system:logs     → monitoring
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from backend.shared.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """Typed payload for all events on the Redis Stream bus."""

    stream: str
    event_id: str  # Redis stream entry ID (e.g. "1234567890123-0")
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.data:
            raise KeyError(f"StreamEvent missing required field '{key}' in stream '{self.stream}'")
        return self.data[key]


class RedisStreamClient:
    """Thin async wrapper over redis-py. Use as a singleton per process."""

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("RedisStreamClient connected to %s", settings.REDIS_URL)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def _r(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("RedisStreamClient not connected — call connect() first.")
        return self._client

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish(self, stream: str, data: dict[str, Any]) -> str:
        """XADD to stream. Values are JSON-encoded if not already strings."""
        payload: dict[str, str] = {}
        for k, v in data.items():
            payload[k] = v if isinstance(v, str) else json.dumps(v, default=str)
        event_id: str = await self._r.xadd(stream, payload)
        logger.debug("Published event %s to %s", event_id, stream)
        return event_id

    # ── Simple consume (no consumer group) ───────────────────────────────────

    async def consume(
        self,
        stream: str,
        last_id: str = "0",
        count: int = 100,
    ) -> list[StreamEvent]:
        """XREAD — stateless read, returns events after last_id."""
        results = await self._r.xread({stream: last_id}, count=count)
        events: list[StreamEvent] = []
        for _stream_name, messages in results:
            for msg_id, raw in messages:
                decoded = _decode_fields(raw)
                events.append(StreamEvent(stream=stream, event_id=msg_id, data=decoded))
        return events

    # ── Consumer group consume ────────────────────────────────────────────────

    async def ensure_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist (idempotent)."""
        try:
            await self._r.xgroup_create(stream, group, id="0", mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> list[StreamEvent]:
        """XREADGROUP — at-least-once delivery with ack support."""
        results = await self._r.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
        events: list[StreamEvent] = []
        if results:
            for _stream_name, messages in results:
                for msg_id, raw in messages:
                    decoded = _decode_fields(raw)
                    events.append(StreamEvent(stream=stream, event_id=msg_id, data=decoded))
        return events

    async def ack(self, stream: str, group: str, *event_ids: str) -> None:
        """XACK — mark events as processed."""
        await self._r.xack(stream, group, *event_ids)


def _decode_fields(raw: dict[str, str]) -> dict[str, Any]:
    """Try JSON-decode each field; fall back to raw string."""
    decoded: dict[str, Any] = {}
    for k, v in raw.items():
        try:
            decoded[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            decoded[k] = v
    return decoded


redis_stream = RedisStreamClient()
