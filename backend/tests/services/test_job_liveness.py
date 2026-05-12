"""
Tests for job URL liveness gate — pattern matching, classification, batch check.
"""
from __future__ import annotations

import pytest

from backend.services.job_liveness import check_liveness, batch_check_liveness
from backend.services.job_status import JobStatus


class TestCheckLiveness:
    def test_http_404_is_dead(self):
        status, reason = check_liveness(404, "some body text", "https://example.com/job/1")
        assert status == JobStatus.DEAD
        assert "404" in reason

    def test_http_410_is_dead(self):
        status, reason = check_liveness(410, "some body text", "https://example.com/job/1")
        assert status == JobStatus.DEAD

    def test_apply_button_is_active(self):
        status, reason = check_liveness(200, "Click Apply Now to submit", "https://example.com/job/1")
        assert status == JobStatus.LIVE
        assert "apply" in reason

    def test_expired_pattern_is_dead(self):
        status, reason = check_liveness(200, "This job has expired and is no longer accepting applications", "https://example.com/job/1")
        assert status == JobStatus.DEAD
        assert "expired" in reason

    def test_greenhouse_error_redirect_is_dead(self):
        status, reason = check_liveness(200, "body", "https://boards.greenhouse.io/jobs/123?error=true")
        assert status == JobStatus.DEAD
        assert "redirect" in reason

    def test_insufficient_content_is_dead(self):
        status, reason = check_liveness(200, "Nav", "https://example.com/job/1")
        assert status == JobStatus.DEAD
        assert "insufficient" in reason

    def test_uncertain_when_no_apply_button(self):
        text = " ".join(["meaningful job description content paragraph"] * 30)
        status, reason = check_liveness(200, text, "https://example.com/job/1")
        assert status == JobStatus.UNCERTAIN
        assert "no_apply" in reason

    def test_position_filled_is_dead(self):
        status, reason = check_liveness(200, "This position has been filled. Thank you for your interest.", "https://example.com/job/1")
        assert status == JobStatus.DEAD
        assert "filled" in reason

    def test_german_expired_is_dead(self):
        status, reason = check_liveness(200, "Diese Stelle ist bereits besetzt", "https://example.com/job/1")
        assert status == JobStatus.DEAD

    def test_french_expired_is_dead(self):
        status, reason = check_liveness(200, "Cette offre n'est plus disponible", "https://example.com/job/1")
        assert status == JobStatus.DEAD

    def test_spanish_apply_is_active(self):
        status, reason = check_liveness(200, "Solicitar ahora", "https://example.com/job/1")
        assert status == JobStatus.LIVE
        assert "apply" in reason

    def test_german_apply_is_active(self):
        status, reason = check_liveness(200, "Jetzt bewerben", "https://example.com/job/1")
        assert status == JobStatus.LIVE
        assert "apply" in reason

    def test_french_apply_is_active(self):
        status, reason = check_liveness(200, "Postuler maintenant", "https://example.com/job/1")
        assert status == JobStatus.LIVE
        assert "apply" in reason

    def test_greenhouse_no_longer_open_is_dead(self):
        status, reason = check_liveness(200, "The job you are looking for is no longer open.", "https://boards.greenhouse.io/jobs/123")
        assert status == JobStatus.DEAD

    def test_workday_listing_redirect_is_dead(self):
        status, reason = check_liveness(200, "663 JOBS FOUND", "https://workday.wd5.myworkdayjobs.com/careers")
        assert status == JobStatus.DEAD

    def test_ashby_start_application_is_active(self):
        status, reason = check_liveness(200, "Click start application to begin", "https://jobs.ashbyhq.com/company/123")
        assert status == JobStatus.LIVE


class TestBatchCheckLiveness:
    def test_batch_adds_liveness_fields(self):
        results = [
            {"url": "https://example.com/1", "body": "Apply Now", "http_status": 200},
            {"url": "https://example.com/2", "body": "This job has expired", "http_status": 200},
        ]
        updated = batch_check_liveness(results)
        assert updated[0]["liveness_status"] == "live"
        assert updated[1]["liveness_status"] == "dead"

    def test_batch_empty_input(self):
        assert batch_check_liveness([]) == []
