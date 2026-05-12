"""
services/auth.py — JWT token lifecycle management.

Provides:
  - create_access_token / create_refresh_token
  - verify_token       — decode and return the subject claim
  - verify_credentials — constant-time credential comparison (no timing attacks)

Credentials are configured via env vars ADMIN_USERNAME / ADMIN_PASSWORD.
Token blocklist is Redis-backed for multi-instance deployments.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from backend.shared.config import settings

# ── Token Blocklist (Redis-backed for multi-instance) ────────────────────────
# Single instance fallback: use in-memory set if Redis is unavailable.
_token_blocklist_inmem: set[str] = set()
_BLOCKLIST_MAX_SIZE = 10_000
_BLOCKLIST_KEY = "leadiq:blocklist"


def _get_redis():
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    except Exception:
        return None


def _redis_blocklist_add(token: str) -> None:
    r = _get_redis()
    if r:
        r.sadd(_BLOCKLIST_KEY, token)
        r.expire(_BLOCKLIST_KEY, 86400)


def _redis_blocklist_check(token: str) -> bool | None:
    r = _get_redis()
    if r:
        return r.sismember(_BLOCKLIST_KEY, token)
    return None


def _prune_inmem_blocklist() -> None:
    if len(_token_blocklist_inmem) > _BLOCKLIST_MAX_SIZE:
        half = sorted(_token_blocklist_inmem)[:_BLOCKLIST_MAX_SIZE // 2]
        _token_blocklist_inmem.difference_update(half)


def revoke_token(token: str) -> None:
    """Add a token to the revocation list. Call on logout."""
    if not token:
        return
    _redis_blocklist_add(token)
    _token_blocklist_inmem.add(token)
    _prune_inmem_blocklist()


def is_token_revoked(token: str) -> bool:
    redis_result = _redis_blocklist_check(token)
    if redis_result is not None:
        return redis_result
    return token in _token_blocklist_inmem


# ── Token creation ────────────────────────────────────────────────────────────

def create_access_token(username: str) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": username, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(username: str) -> str:
    expire = datetime.now(UTC) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {"sub": username, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ── Token verification ────────────────────────────────────────────────────────

def verify_token(token: str, expected_type: str = "access") -> str:
    """Decode JWT and return the username (sub). Raises ValueError on failure."""
    if expected_type == "refresh" and is_token_revoked(token):
        raise ValueError("Refresh token has been revoked")

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc

    sub = payload.get("sub")
    if not sub:
        raise ValueError("Token missing subject claim")

    tok_type = payload.get("type", "access")
    if tok_type != expected_type:
        raise ValueError(f"Expected {expected_type} token, got {tok_type}")

    return str(sub)


# ── Credential verification ───────────────────────────────────────────────────

def verify_credentials(username: str, password: str) -> bool:
    """Constant-time credential check — safe against timing attacks."""
    valid_user = secrets.compare_digest(
        username.encode(), settings.ADMIN_USERNAME.encode()
    )
    valid_pass = secrets.compare_digest(
        password.encode(), settings.ADMIN_PASSWORD.encode()
    )
    return valid_user and valid_pass
