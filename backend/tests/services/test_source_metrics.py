"""
Tests for source metrics collector — per-source tracking and summary.
"""
from __future__ import annotations

import pytest

from backend.services.source_metrics import SourceMetrics, MetricsCollector


class TestSourceMetrics:
    def test_timeout_rate(self):
        m = SourceMetrics(source="test")
        m.record_request(success=True)
        m.record_request(success=False, timeout=True)
        assert m.timeout_rate == 0.5

    def test_success_rate(self):
        m = SourceMetrics(source="test")
        m.record_request(success=True)
        m.record_request(success=True)
        m.record_request(success=False, blocked=True)
        assert m.success_rate == pytest.approx(2 / 3)

    def test_avg_conversion_score(self):
        m = SourceMetrics(source="test")
        m.record_conversion_score(0.8)
        m.record_conversion_score(0.6)
        assert m.avg_conversion_score == 0.7

    def test_liveness_tracking(self):
        m = SourceMetrics(source="test")
        m.record_liveness("live")
        m.record_liveness("dead")
        m.record_liveness("uncertain")
        assert m.active_links == 1
        assert m.expired_links == 1
        assert m.uncertain_links == 1

    def test_to_dict(self):
        m = SourceMetrics(source="indeed")
        m.record_request(success=True, response_time_ms=100)
        m.record_liveness("live")
        d = m.to_dict()
        assert d["source"] == "indeed"
        assert d["requests"] == 1
        assert d["active_links"] == 1

    def test_avg_response_time(self):
        m = SourceMetrics(source="test")
        m.record_request(success=True, response_time_ms=100)
        m.record_request(success=True, response_time_ms=300)
        assert m.avg_response_time_ms == 200


class TestMetricsCollector:
    def test_for_source_creates_on_demand(self):
        c = MetricsCollector()
        m = c.for_source("indeed")
        assert m.source == "indeed"

    def test_record_delegates(self):
        c = MetricsCollector()
        c.record("indeed", success=True, response_time_ms=50)
        assert c.for_source("indeed").requests == 1

    def test_summary_returns_all(self):
        c = MetricsCollector()
        c.record("indeed", success=True)
        c.record("naukri", success=False, blocked=True)
        s = c.summary()
        assert "indeed" in s
        assert "naukri" in s
