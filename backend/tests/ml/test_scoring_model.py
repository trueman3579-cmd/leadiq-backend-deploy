"""Tests for GradientBoostingScorer — encoding helpers."""
from __future__ import annotations

import pytest

from backend.ml.scoring_model import GradientBoostingScorer


class TestEncodeSource:
    """Verify source encoding matches SOURCE_ENCODING trust map."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("naukri", 10.0),
            ("internshala", 9.0),
            ("linkedin", 8.0),
            ("dpiit", 7.0),
            ("mca21", 6.0),
            ("gem", 5.0),
            ("msme", 5.0),
            ("reddit", 3.0),
            ("hn", 3.0),
            ("github", 2.0),
            ("twitter", 1.0),
        ],
    )
    def test_known_sources(
        self, source: str, expected: float
    ) -> None:
        result = GradientBoostingScorer._encode_source(source)
        assert result == expected

    def test_unknown_source_returns_zero(self) -> None:
        result = GradientBoostingScorer._encode_source("unknown_source")
        assert result == 0.0

    def test_empty_source_returns_zero(self) -> None:
        result = GradientBoostingScorer._encode_source("")
        assert result == 0.0


class TestEncodeStatus:
    """Verify status encoding matches STATUS_ENCODING map."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("closed_won", 10.0),
            ("qualified", 8.0),
            ("contacted", 5.0),
            ("new", 3.0),
            ("closed_lost", 0.0),
        ],
    )
    def test_known_statuses(
        self, status: str, expected: float
    ) -> None:
        result = GradientBoostingScorer._encode_status(status)
        assert result == expected

    def test_unknown_status_returns_zero(self) -> None:
        result = GradientBoostingScorer._encode_status("unknown")
        assert result == 0.0

    def test_empty_status_returns_zero(self) -> None:
        result = GradientBoostingScorer._encode_status("")
        assert result == 0.0


class TestEncodeLocationTier:
    """Verify location tier encoding maps cities correctly."""

    @pytest.mark.parametrize(
        "city",
        [
            "Bangalore",
            "bengaluru",
            "Hyderabad",
            "Mumbai",
            "Delhi",
            "new delhi",
            "Pune",
            "Chennai",
        ],
    )
    def test_tier_1_city_returns_3(self, city: str) -> None:
        result = GradientBoostingScorer._encode_location_tier(city)
        assert result == 3.0, f"{city} should be tier 1"

    @pytest.mark.parametrize(
        "city",
        [
            "Kolkata",
            "Ahmedabad",
            "Jaipur",
            "Indore",
            "Nagpur",
            "Surat",
            "Lucknow",
        ],
    )
    def test_tier_2_city_returns_2(self, city: str) -> None:
        result = GradientBoostingScorer._encode_location_tier(city)
        assert result == 2.0, f"{city} should be tier 2"

    def test_other_city_returns_1(self) -> None:
        result = GradientBoostingScorer._encode_location_tier("Patna")
        assert result == 1.0

    def test_empty_location_returns_1(self) -> None:
        result = GradientBoostingScorer._encode_location_tier("")
        assert result == 1.0

    def test_location_with_extra_text(self) -> None:
        """Location strings that contain a tier-1 city should still match."""
        result = GradientBoostingScorer._encode_location_tier(
            "Bangalore, Karnataka, India"
        )
        assert result == 3.0
