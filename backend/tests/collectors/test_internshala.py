"""Tests for InternshalaCollector — stipend parsing, ID extraction."""
from __future__ import annotations

import pytest

from backend.collectors.internshala import InternshalaCollector


class TestInternshalaCollectorSource:
    """Verify the static source attribute."""

    def test_source_is_internshala(self) -> None:
        assert InternshalaCollector.source == "internshala"

    def test_instance_source_matches_class(self) -> None:
        collector = InternshalaCollector()
        assert collector.source == "internshala"


class TestParseStipend:
    """Verify _parse_stipend handles Indian stipend formats."""

    @pytest.mark.parametrize(
        ("stipend_str", "expected"),
        [
            # Standard range
            ("10,000-15,000", (10_000, 15_000)),
            ("₹10,000-₹15,000", (10_000, 15_000)),
            # Single value
            ("5,000", (5_000, 5_000)),
            ("₹5,000", (5_000, 5_000)),
            # K suffix
            ("10K - 15K", (10_000, 15_000)),
            ("10k - 15k", (10_000, 15_000)),
            # Unpaid / empty
            ("Unpaid", (None, None)),
            ("", (None, None)),
            ("NA", (None, None)),
        ],
    )
    def test_parse_stipend(
        self, stipend_str: str, expected: tuple[int | None, int | None]
    ) -> None:
        result = InternshalaCollector._parse_stipend(stipend_str)
        assert result == expected


class TestExtractId:
    """Verify _extract_id pulls IDs from Internshala URLs."""

    def test_standard_detail_url(self) -> None:
        url = (
            "https://internshala.com/internship/detail/"
            "software-development-internship123"
        )
        result = InternshalaCollector._extract_id(url)
        assert result == "software-development-internship123"

    def test_url_with_trailing_slash(self) -> None:
        url = "https://internshala.com/internship/detail/abc123xyz/"
        result = InternshalaCollector._extract_id(url)
        assert result == "abc123xyz"

    def test_numeric_id_pattern(self) -> None:
        url = "https://internshala.com/internships/internship_12345"
        result = InternshalaCollector._extract_id(url)
        assert result == "12345"

    def test_relative_path(self) -> None:
        path = "/internship/detail/data-science-intern-mumbai"
        result = InternshalaCollector._extract_id(path)
        assert result == "data-science-intern-mumbai"

    def test_unknown_format_falls_back_to_hash(self) -> None:
        url = "https://internshala.com/some-other/page"
        result = InternshalaCollector._extract_id(url)
        assert isinstance(result, str)
        assert len(result) == 12  # md5 hexdigest[:12]
