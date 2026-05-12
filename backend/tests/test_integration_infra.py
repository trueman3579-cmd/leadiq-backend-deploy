from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
def test_postgres_and_redis_containers_boot() -> None:
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    with PostgresContainer("postgres:16-alpine") as postgres, RedisContainer("redis:7-alpine") as redis:
        assert postgres.get_connection_url()
        assert redis.get_connection_url()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_upgrade_creates_expected_tables() -> None:
    from alembic.command import upgrade
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as postgres:
        sync_url = postgres.get_connection_url()
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")

        os.environ["DATABASE_URL"] = async_url

        alembic_cfg = Config("backend/alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", async_url)
        upgrade(alembic_cfg, "head")

        engine = create_async_engine(async_url)
        async with engine.begin() as connection:
            result = await connection.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_name in ('posts', 'leads', 'feedback', 'quota_usage')"
                )
            )
            assert result.scalar() == 4
        await engine.dispose()
        os.environ.pop("DATABASE_URL", None)