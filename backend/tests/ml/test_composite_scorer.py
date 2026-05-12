"""Tests for CompositeScorer — band classification and action recommendation."""
from __future__ import annotations

import pytest

from backend.ml.composite_scorer import CompositeScorer


class TestClassifyBand:
    """Verify band classification at score boundaries."""

    @pytest.mark.parametrize(
        ("score", "expected_band"),
        [
            (100.0, "hot"),
            (75.0, "hot"),
            (74.9, "warm"),
            (50.0, "warm"),
            (49.9, "cool"),
            (25.0, "cool"),
            (24.9, "cold"),
            (0.0, "cold"),
        ],
    )
    def test_classify_band_at_boundaries(
        self, score: float, expected_band: str
    ) -> None:
        band = CompositeScorer._classify_band(score)
        assert band == expected_band


class TestRecommendAction:
    """Verify recommended actions map correctly to each band."""

    @pytest.mark.parametrize(
        ("band", "expected_action"),
        [
            ("hot", "immediate_outreach"),
            ("warm", "nurture_sequence"),
            ("cool", "long_term_nurture"),
            ("cold", "drip_campaign"),
        ],
    )
    def test_recommend_action_for_each_band(
        self, band: str, expected_action: str
    ) -> None:
        action = CompositeScorer._recommend_action(band)
        assert action == expected_action

    def test_unknown_band_returns_review(self) -> None:
        action = CompositeScorer._recommend_action("unknown_band")
        assert action == "review"
