"""Feature flags for actors"""
import structlog

logger = structlog.get_logger()
_r = None

try:
    from backend.shared.stream import redis_stream
    _r = redis_stream._r
except:
    pass

ACTOR_FLAGS = {
    "tracxn": "actors:tracxn:enabled",
    "dpiit": "actors:dpiit:enabled",
    "mca21": "actors:mca21:enabled",
    "telegram": "actors:telegram:enabled",
    "github": "actors:github:enabled",
    "hn": "actors:hn:enabled",
    "producthunt": "actors:producthunt:enabled",
    "naukri": "actors:naukri:enabled",
    "internshala": "actors:internshala:enabled",
}


def is_actor_enabled(actor: str) -> bool:
    """Check if actor is enabled (default ON)"""
    if not _r:
        return True  # Default ON if Redis not available
    val = _r.get(ACTOR_FLAGS.get(actor, f"actors:{actor}:enabled"))
    return val is None or val == "1"


def set_actor_enabled(actor: str, enabled: bool):
    """Set actor enabled state"""
    if not _r:
        return
    key = ACTOR_FLAGS.get(actor, f"actors:{actor}:enabled")
    _r.set(key, "1" if enabled else "0")
    logger.info("feature_flag_updated", actor=actor, enabled=enabled)
