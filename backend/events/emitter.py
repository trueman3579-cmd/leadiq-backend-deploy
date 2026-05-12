"""
Domain event emitter - Redis Streams for events
"""
import json
import structlog
from datetime import datetime, UTC

logger = structlog.get_logger()
_r = None

try:
    from backend.shared.stream import redis_stream
    _r = redis_stream._r
except:
    pass

STREAMS = {
    "lead_created": "leadiq:events:lead_created",
    "lead_enriched": "leadiq:events:lead_enriched",
    "lead_scored": "leadiq:events:lead_scored",
    "signal_detected": "leadiq:events:signal_detected",
    "lead_ranked": "leadiq:events:lead_ranked",
}


async def emit(event_type: str, payload: dict, maxlen: int = 50_000):
    """Emit domain event to Redis Stream"""
    if not _r:
        return
    stream = STREAMS.get(event_type)
    if not stream:
        raise ValueError(f"Unknown event type: {event_type}")
    await _r.xadd(stream, {
        "event_type": event_type,
        "payload": json.dumps(payload),
        "emitted_at": datetime.now(UTC).isoformat(),
    }, maxlen=maxlen)
    logger.info("event_emitted", type=event_type, stream=stream)
