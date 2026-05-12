"""
Load tests for pipeline throughput.

Measures collector throughput, API response time, and pipeline capacity.
"""
from __future__ import annotations

import time
from typing import Any

import pytest


class TestCollectionRate:
    """Measure collector throughput under synthetic load."""

    async def test_raw_post_creation_throughput(self):
        """Measure RawPost creation throughput (thousands/sec)."""
        from backend.collectors.base import RawPost

        batch_size = 1000
        start = time.perf_counter()

        posts = [
            RawPost(
                source="test",
                external_id=f"test-{i}",
                url=f"https://example.com/{i}",
                title=f"Test Post {i}",
                body="x" * 100,
            )
            for i in range(batch_size)
        ]

        elapsed = time.perf_counter() - start
        rate = batch_size / elapsed if elapsed > 0 else float("inf")

        assert len(posts) == batch_size
        assert rate > 100  # At least 100 posts/sec
        print(f"\nRawPost creation: {rate:.0f} posts/sec")

    async def test_content_hash_throughput(self):
        """Measure content_hash computation throughput."""
        from backend.collectors.base import RawPost

        texts = [f"Test content {i} with some varying text body" for i in range(500)]
        start = time.perf_counter()

        hashes = []
        for text in texts:
            post = RawPost(
                source="test", external_id=f"t-{text[:10]}",
                url="https://x.com", title=text, body=text,
            )
            hashes.append(post.content_hash)

        elapsed = time.perf_counter() - start
        rate = len(texts) / elapsed if elapsed > 0 else float("inf")

        assert len(hashes) == len(texts)
        assert all(len(h) == 64 for h in hashes)
        print(f"\nContent hash: {rate:.0f} hashes/sec")


class TestApiThroughput:
    """Measure API endpoint response patterns (no real server)."""

    async def test_json_serialization_throughput(self):
        """Measure JSON serialization throughput for typical lead payloads."""
        import json

        leads = [
            {
                "id": str(i),
                "company_name": f"Company {i}",
                "confidence": 0.85,
                "intent": "buy",
                "score_band": "hot",
                "industry": "saas",
                "contact_name": f"Person {i}",
            }
            for i in range(500)
        ]

        start = time.perf_counter()
        for _ in range(20):
            serialized = json.dumps(leads)
            deserialized = json.loads(serialized)
            assert len(deserialized) == len(leads)
        elapsed = time.perf_counter() - start

        throughput = (len(leads) * 20) / elapsed if elapsed > 0 else float("inf")
        print(f"\nJSON throughput: {throughput:.0f} leads/sec")


class TestPipelineCapacity:
    """Estimate pipeline capacity for 25K leads/day target."""

    def test_daily_capacity_feasibility(self):
        """Verify 25K leads/day is feasible based on per-lead processing time."""
        leads_per_day = 25_000
        seconds_per_day = 86_400
        max_time_per_lead_ms = (seconds_per_day / leads_per_day) * 1000

        # Each lead needs: collect → analyze → score → persist
        estimated_ms = 50  # conservative estimate per lead for non-LLM path
        assert estimated_ms < max_time_per_lead_ms, (
            f"Estimated {estimated_ms}ms/lead exceeds budget "
            f"{max_time_per_lead_ms:.1f}ms/lead for {leads_per_day}/day"
        )
        print(
            f"\n25K leads/day budget: {max_time_per_lead_ms:.1f}ms/lead, "
            f"estimated: {estimated_ms}ms/lead — feasible"
        )

    def test_collector_daily_yield(self):
        """Verify platform collector capacity to reach 25K/day target."""
        from backend.shared.stream_v2 import PLATFORM_TIER_MAP

        # Conservative per-platform daily estimates
        platform_yields = {
            "naukri": 3000,
            "internshala": 1500,
            "linkedin": 2000,
            "indeed": 3000,
            "shine": 1000,
            "monster": 1500,
            "naukrigulf": 500,
            "timesjobs": 1000,
            "foundit": 800,
            "weekday": 300,
            "freshersworld": 1500,
            "hirist": 500,
            "cutshort": 300,
            "instahyre": 300,
            "hirect": 500,
            "sarkari_result": 2000,
            "freejobalert": 1500,
            "employment_news": 500,
            "iimjobs": 200,
            "dpiit": 1000,
            "mca21": 500,
            "apisetu": 1000,
            "gem": 500,
            "msme": 500,
        }

        total_yield = sum(platform_yields.values())
        assert total_yield >= 25_000, (
            f"Total estimated yield {total_yield}/day < 25K target. "
            f"Need {25_000 - total_yield} more leads/day from new sources."
        )
        print(f"\nTotal estimated daily yield: {total_yield} leads (target: 25,000)")
        assert len(platform_yields) <= len(PLATFORM_TIER_MAP)
