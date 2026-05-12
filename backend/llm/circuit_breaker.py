"""Circuit breaker for Gemini API"""
import time
from enum import Enum
import structlog
import redis

logger = structlog.get_logger()
_r = None

try:
    _r = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
except:
    pass

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

CB_KEY = "gemini:circuit:{}"

def get_state(name: str = "gemini") -> CircuitState:
    if not _r:
        return CircuitState.CLOSED
    val = _r.hgetall(CB_KEY.format(name))
    if not val:
        return CircuitState.CLOSED
    state = val.get("state", "closed")
    last_failure = float(val.get("last_failure", 0))
    recovery_timeout = float(val.get("recovery_timeout", 60))
    if state == "open" and time.time() - last_failure > recovery_timeout:
        return CircuitState.HALF_OPEN
    return CircuitState(state)

def record_success(name: str = "gemini"):
    if not _r:
        return
    _r.hset(CB_KEY.format(name), mapping={"state": "closed", "failures": 0})

def record_failure(name: str = "gemini", threshold: int = 5, recovery_timeout: int = 60):
    if not _r:
        return
    key = CB_KEY.format(name)
    failures = int(_r.hget(key, "failures") or 0) + 1
    _r.hset(key, mapping={"failures": failures, "last_failure": time.time(), "recovery_timeout": recovery_timeout})
    if failures >= threshold:
        _r.hset(key, mapping={"state": CircuitState.OPEN.value, "last_failure": time.time()})
        _r.expire(key, recovery_timeout * 3)
        logger.error("circuit_opened", name=name, failures=failures)
