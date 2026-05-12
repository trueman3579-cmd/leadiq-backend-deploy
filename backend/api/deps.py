"""
api/deps.py — FastAPI dependency injectors.
Import these in route handlers via Depends().

Usage:
  @router.get("/leads")
  async def list_leads(session: DbSession, stream: StreamClient):
      ...
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.db import AsyncSessionLocal
from backend.shared.stream import redis_stream, RedisStreamClient
from backend.services.auth import verify_token


# ── DB session ────────────────────────────────────────────────────────────────

async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a DB session, handling connection failures gracefully."""
    session: AsyncSession | None = None
    try:
        session = AsyncSessionLocal()
        async with session:
            yield session
            await session.commit()
    except Exception:
        if session:
            await session.rollback()
        raise


DbSession = Annotated[AsyncSession, Depends(_get_db)]


# ── Redis stream client ───────────────────────────────────────────────────────

async def _get_stream() -> RedisStreamClient:
    return redis_stream


StreamClient = Annotated[RedisStreamClient, Depends(_get_stream)]


# ── JWT auth ──────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


async def _get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Extract and validate the Bearer JWT. Raises 401 if missing or invalid."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        username = verify_token(credentials.credentials, expected_type="access")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return username


async def _get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str | None:
    """Return username if a valid JWT is present, else None (no error)."""
    if not credentials:
        return None
    try:
        return verify_token(credentials.credentials, expected_type="access")
    except ValueError:
        return None


CurrentUser    = Annotated[str, Depends(_get_current_user)]
OptionalUser   = Annotated[str | None, Depends(_get_optional_user)]
