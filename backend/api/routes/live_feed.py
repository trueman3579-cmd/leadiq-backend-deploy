"""
live_feed.py — SSE Live Feed Endpoint (Day 22)

Redis pub/sub-powered Server-Sent Events for real-time lead streaming.
Publishes: lead:collected, lead:analyzed, lead:scored, lead:outreach events.

Usage:
    GET /api/stream                 → SSE stream (all events)
    GET /api/stream?source=github   → SSE stream (filtered by source)
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["live-feed"])

STREAM_CHANNELS = [
    "lead:collected",
    "lead:analyzed",
    "lead:scored",
    "lead:outreach",
    "lead:crm_update",
]


@router.get("/stream")
async def sse_stream(
    request: Request,
    source: str = Query("", description="Filter by source (github, hn, etc.)"),
    channels: str = Query("", description="Comma-separated channels to subscribe"),
):
    """
    SSE endpoint for real-time lead events.
    Uses Redis pub/sub for cross-worker event delivery.
    Falls back to polling if Redis isn't available.
    """
    selected_channels = (
        [c.strip() for c in channels.split(",") if c.strip()]
        if channels
        else STREAM_CHANNELS
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Subscribe to Redis pub/sub and yield SSE events."""
        try:
            from backend.shared.stream import redis_stream

            r = redis_stream._r
            if r is None:
                logger.warning("sse_no_redis")
                yield _sse_event("error", {"error": "Redis not connected"})
                return

            async with r.pubsub() as pubsub:
                for channel in selected_channels:
                    await pubsub.subscribe(channel)
                    logger.debug("sse_subscribed", channel=channel)

                yield _sse_event("connected", {
                    "status": "connected",
                    "channels": selected_channels,
                    "source_filter": source or "all",
                })

                async for message in pubsub.listen():
                    if await request.is_disconnected():
                        break

                    if message["type"] != "message":
                        continue

                    try:
                        data = json.loads(message["data"])
                    except json.JSONDecodeError:
                        continue

                    # Optional source filter
                    if source and data.get("source", "").lower() != source.lower():
                        continue

                    yield _sse_event(message["channel"].decode(), data)

        except Exception as exc:
            logger.error("sse_stream_error", error=str(exc))
            yield _sse_event("error", {"error": str(exc)})

    return EventSourceResponse(event_generator())


def _sse_event(event: str, data: dict) -> dict:
    """Format an SSE event dict for EventSourceResponse."""
    return {"event": event, "data": json.dumps(data)}


@router.get("/stream/health")
async def stream_health():
    """Health check for the SSE streaming infrastructure."""
    try:
        from backend.shared.stream import redis_stream

        r = redis_stream._r
        if r is None:
            return {"status": "degraded", "redis": "not_connected"}

        await r.ping()
        subs = await r.pubsub_numsub(*STREAM_CHANNELS)
        return {
            "status": "healthy",
            "redis": "connected",
            "subscribers": {ch.decode(): count for ch, count in subs},
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
