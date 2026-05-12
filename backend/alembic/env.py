"""Alembic environment configuration."""
from __future__ import annotations

import os
import sys
from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add the project root to the path for imports (backend/ is under it)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.shared.db import Base
from backend.shared.config import settings
from backend.shared.models import Post, Lead, Feedback, QuotaUsage, UserProfile, CompanyContext, GovScheme, FundingEvent, JobSignal  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = settings.DATABASE_URL or os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    async def _run_migrations() -> None:
        connectable = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        async with connectable.connect() as connection:
            await connection.run_sync(
                lambda sync_connection: context.configure(
                    connection=sync_connection,
                    target_metadata=target_metadata,
                )
            )
            await connection.run_sync(
                lambda sync_connection: _run_migrations_sync(sync_connection)
            )

        await connectable.dispose()

    run(_run_migrations())


def _run_migrations_sync(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
