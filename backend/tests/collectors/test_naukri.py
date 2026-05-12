"""Tests for NaukriCollector — salary parsing, experience parsing, source attribute."""
from __future__ import annotations

import pytest

from backend.collectors.naukri import NaukriCollector


class TestNaukriCollectorSource:
    """Verify the static source attribute."""

    def test_source_is_naukri(self) -> None:
        assert NaukriCollector.source == "naukri"

    def test_instance_source_matches_class(self) -> None:
        collector = NaukriCollector()
        assert collector.source == "naukri"


class TestParseSalary:
    """Verify _parse_salary handles Indian salary formats correctly."""

    @pytest.mark.parametrize(
        ("salary_str", "expected"),
        [
            # Standard ranges
            ("₹5-10 LPA", (500_000, 1_000_000)),
            ("₹5 Lacs - 10 Lacs", (500_000, 1_000_000)),
            # Single value
            ("₹15 Lacs P.A.", (1_500_000, 1_500_000)),
            # Not disclosed
            ("Not Disclosed", (None, None)),
            ("", (None, None)),
            ("NA", (None, None)),
            # Monthly salary (annualised)
            ("₹50K - 80K/monthly", (600_000, 960_000)),
            ("₹50K - 80K /month", (600_000, 960_000)),
            # Large numbers (already annual)
            ("₹1200000 - 1800000", (1_200_000, 1_800_000)),
        ],
    )
    def test_parse_salary(
        self, salary_str: str, expected: tuple[int | None, int | None]
    ) -> None:
        result = NaukriCollector._parse_salary(salary_str)
        assert result == expected


class TestParseExperience:
    """Verify _parse_experience parses Indian experience formats."""

    @pytest.mark.parametrize(
        ("exp_str", "expected"),
        [
            ("2-5 yrs", (2, 5)),
            ("5+", (5, 5)),
            ("3", (3, 3)),
            ("", (None, None)),
            ("0-1 yr", (0, 1)),
            ("10+ years", (10, 10)),
        ],
    )
    def test_parse_experience(
        self, exp_str: str, expected: tuple[int | None, int | None]
    ) -> None:
        result = NaukriCollector._parse_experience(exp_str)
        assert result == expected
