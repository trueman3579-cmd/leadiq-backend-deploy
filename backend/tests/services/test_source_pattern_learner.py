"""
Tests for source pattern learner — domain tracking, fetch mode selection.
"""
from __future__ import annotations

import pytest

from backend.services.source_pattern_learner import SourcePatternLearner, DomainProfile


class TestDomainProfile:
    def test_success_rate(self):
        p = DomainProfile("indeed.com")
        p.record(success=True)
        p.record(success=False, blocked=True)
        assert p.success_rate == 0.5
        assert p.blocked_rate == 0.5

    def test_suggested_mode_stealth_when_blocked(self):
        p = DomainProfile("linkedin.com")
        for _ in range(5):
            p.record(success=False, blocked=True)
        assert p.suggested_fetch_mode() == "stealth"

    def test_suggested_mode_static_when_good(self):
        p = DomainProfile("cutshort.io")
        for _ in range(10):
            p.record(success=True)
        assert p.suggested_fetch_mode() == "static"

    def test_suggested_mode_stealth_when_blocked_more_than_2(self):
        p = DomainProfile("naukri.com")
        for _ in range(2):
            p.record(success=True)
        for _ in range(4):
            p.record(success=False, blocked=True)
        assert p.suggested_fetch_mode() == "stealth"

    def test_avg_response_time(self):
        p = DomainProfile("test.com")
        p.record(success=True, response_time_ms=100)
        p.record(success=True, response_time_ms=200)
        assert p.avg_response_time_ms == 150.0


class TestSourcePatternLearner:
    def test_extract_domain(self):
        learner = SourcePatternLearner()
        assert learner._extract_domain("https://in.indeed.com/jobs?q=test") == "in.indeed.com"
        assert learner._extract_domain("unknown") == "unknown"

    def test_classify_data_type(self):
        learner = SourcePatternLearner()
        assert learner._classify_data_type({"salary", "company"}) == "jobs"
        assert learner._classify_data_type({"title", "content"}) == "general"

    def test_get_profile_creates_on_first_access(self):
        learner = SourcePatternLearner()
        profile = learner.get_profile("https://example.com")
        assert profile.domain == "example.com"
        assert profile.total_requests == 0

    def test_record_result_updates_metrics(self):
        learner = SourcePatternLearner()
        learner.record_result("https://indeed.com/job/1", "success", 100)
        profile = learner.get_profile("https://indeed.com/job/1")
        assert profile.total_requests == 1
        assert profile.successful == 1

    def test_record_result_tracks_blocked(self):
        learner = SourcePatternLearner()
        learner.record_result("https://linkedin.com/job/1", "blocked", 50)
        profile = learner.get_profile("https://linkedin.com/job/1")
        assert profile.blocked == 1
        assert profile.blocked_rate == 1.0

    def test_suggest_fetch_mode_adapts(self):
        learner = SourcePatternLearner()
        url = "https://linkedin.com/jobs/1"
        mode1 = learner.suggest_fetch_mode(url)
        for _ in range(5):
            learner.record_result(url, "blocked", 100)
        mode2 = learner.suggest_fetch_mode(url)
        assert mode2 == "stealth"

    def test_get_field_suggestions_for_jobs(self):
        learner = SourcePatternLearner()
        suggestions = learner.get_field_suggestions("https://indeed.com", {"salary", "company"})
        fields = {s["field"] for s in suggestions}
        assert "title" in fields
        assert "company" in fields
        assert "salary" in fields

    def test_summary_returns_all_profiles(self):
        learner = SourcePatternLearner()
        learner.record_result("https://site1.com/job/1", "success")
        learner.record_result("https://site2.com/job/1", "blocked")
        summary = learner.summary()
        assert "site1.com" in summary
        assert "site2.com" in summary
