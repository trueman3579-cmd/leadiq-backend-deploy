"""Tests for deduplication — content_hash consistency and duplicate detection."""
from __future__ import annotations

import hashlib

import pytest

from backend.services.dedup_service import similarity_score


# ── Content Hash Helper ────────────────────────────────────────────────────


def content_hash(text: str) -> str:
    """Compute a deterministic content hash for dedup matching.

    This matches the canonical hashing strategy used in the pipeline:
    SHA-256 of the normalized (lowercased, whitespace-collapsed) text.
    """
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class TestContentHash:
    """Verify content_hash generation is deterministic and consistent."""

    def test_same_text_produces_same_hash(self) -> None:
        text = "We need a better analytics platform"
        h1 = content_hash(text)
        h2 = content_hash(text)
        assert h1 == h2

    def test_case_insensitive_normalization(self) -> None:
        assert content_hash("Hello World") == content_hash("hello world")

    def test_whitespace_normalization(self) -> None:
        assert content_hash("  hello  world  ") == content_hash("hello world")

    def test_different_text_produces_different_hash(self) -> None:
        assert content_hash("lead one") != content_hash("lead two")

    def test_hash_format(self) -> None:
        h = content_hash("test")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)


class TestDuplicateDetection:
    """Verify duplicate detection via content hash comparison."""

    def test_identical_text_is_duplicate(self) -> None:
        text = "Looking for a CRM for our startup"
        h1 = content_hash(text)
        h2 = content_hash(text)
        assert h1 == h2

    def test_identical_with_case_difference_is_duplicate(self) -> None:
        raw = "Looking for a CRM for our startup"
        normalized = "looking for a crm for our startup"
        assert content_hash(raw) == content_hash(normalized)

    def test_different_text_is_not_duplicate(self) -> None:
        h1 = content_hash("Need help with analytics")
        h2 = content_hash("Looking for a CRM")
        assert h1 != h2

    def test_empty_string(self) -> None:
        h = content_hash("")
        assert isinstance(h, str)
        assert len(h) == 64


class TestSimilarityScore:
    """Verify fuzzy string similarity from the dedup service."""

    def test_identical_strings(self) -> None:
        assert similarity_score("Acme Corp", "Acme Corp") == 1.0

    def test_completely_different(self) -> None:
        assert similarity_score("Acme Corp", "Globex Inc") < 1.0

    def test_empty_first_string(self) -> None:
        assert similarity_score("", "Acme Corp") == 0.0

    def test_empty_second_string(self) -> None:
        assert similarity_score("Acme Corp", "") == 0.0

    def test_both_empty(self) -> None:
        assert similarity_score("", "") == 0.0

    def test_typo_variation(self) -> None:
        score = similarity_score("Acme Corporation", "Acme Corp")
        assert 0.0 < score < 1.0
        assert score > 0.5  # close enough to be suspicious
