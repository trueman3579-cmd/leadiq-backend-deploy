"""
shared/db.py — Async SQLAlchemy session factory.
Usage: `async with get_db_session() as session:`
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.shared.config import settings

from sqlalchemy.pool import NullPool

# Support Supavisor transaction pooler override via DISABLE_SUPAVISOR_PORT env
_use_supavisor = os.getenv("DISABLE_SUPAVISOR_PORT", "").lower() not in ("1", "true", "yes")
_raw_url = settings.DATABASE_URL
if _use_supavisor:
    _db_url = (
        _raw_url
        .replace("postgresql://", "postgresql+asyncpg://")
        .replace(":5432/", ":6543/")
        .replace(":5433/", ":6543/")
    )
else:
    _db_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    _db_url,
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "command_timeout": 30,
        "server_settings": {"jit": "off", "application_name": "leadiq_api"},
    },
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base — import this in models.py to register all ORM classes."""
    pass


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a managed async SQLAlchemy session with automatic rollback on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
