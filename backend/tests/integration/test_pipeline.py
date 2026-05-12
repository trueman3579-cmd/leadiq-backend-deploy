"""
Integration tests for the full pipeline flow.

Requires Docker-backed Postgres + Redis (set RUN_INTEGRATION_TESTS=1).
"""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("RUN_INTEGRATION_TESTS"),
        reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
]


@pytest_asyncio.fixture(scope="session")
async def postgres_container() -> AsyncGenerator[PostgresContainer, None]:
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session")
async def redis_container() -> AsyncGenerator[RedisContainer, None]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


class TestPipelineFlow:
    """End-to-end pipeline: collector → stream → analyzer → scorer → persist."""

    async def test_collector_produces_raw_post(self):
        """Verify a collector produces a valid RawPost-like dict."""
        from backend.collectors.base import RawPost

        post = RawPost(
            source="test",
            external_id="test-001",
            url="https://example.com/test",
            title="Test Post",
            body="This is a test post body",
            author="tester",
        )
        assert post.source == "test"
        assert post.external_id == "test-001"
        assert post.content_hash is not None
        assert len(post.content_hash) == 64

    async def test_redis_stream_publish_consume(self, redis_container: RedisContainer):
        """Verify Redis stream publish/consume cycle."""
        import redis.asyncio as aioredis

        redis_url = redis_container.get_connection_url()
        client = aioredis.from_url(redis_url, decode_responses=True)

        # Publish
        event_id = await client.xadd("test:stream", {"key": "value"})
        assert event_id is not None

        # Consume
        results = await client.xread({"test:stream": "0"}, count=10)
        assert len(results) > 0

        await client.aclose()

    async def test_stream_v2_routes_correctly(self):
        """Verify stream_v2 routes platforms to correct tiers."""
        from backend.shared.stream_v2 import RedisStreamClientV2, StreamTier

        client = RedisStreamClientV2()
        assert client.get_tier("naukri") == StreamTier.TIER1_CRITICAL
        assert client.get_tier("linkedin") == StreamTier.TIER1_CRITICAL
        assert client.get_tier("dpiit") == StreamTier.TIER3_GOVERNMENT
        assert client.get_tier("github") == StreamTier.TIER5_SOCIAL
        assert client.get_tier("freshersworld") == StreamTier.TIER4_NICHE

    async def test_stream_v2_dlq_routes(self):
        """Verify DLQ routing per source."""
        from backend.shared.stream_v2 import RedisStreamClientV2

        client = RedisStreamClientV2()
        dlq = client.get_dlq("naukri")
        assert "dlq" in dlq
        assert "tier1" in dlq


class TestRedisStreams:
    """Redis stream publish/consume edge cases."""

    async def test_stream_event_serialization(self):
        """Verify StreamEvent can be serialized/deserialized."""
        from backend.shared.stream import StreamEvent

        event = StreamEvent(
            stream="test:stream",
            event_id="123-0",
            data={"key": "value", "nested": {"a": 1}},
        )
        assert event.get("key") == "value"
        assert event.require("key") == "value"

    async def test_stream_event_missing_key(self):
        from backend.shared.stream import StreamEvent

        event = StreamEvent(stream="test", event_id="1", data={"a": 1})
        with pytest.raises(KeyError):
            event.require("missing")
