"""Tests for RAG embedder fallback."""

import pytest
from backend.services.rag_embedder import get_embedder


def test_embedder_singleton():
    e1 = get_embedder()
    e2 = get_embedder()
    assert e1 is e2


def test_embed_single():
    embedder = get_embedder()
    vec = embedder.embed_single("Hello world")
    assert len(vec) == 384


def test_embed_batch():
    embedder = get_embedder()
    vecs = embedder.embed(["Hello", "World"])
    assert len(vecs) == 2
    assert all(len(v) == 384 for v in vecs)


def test_embed_empty():
    embedder = get_embedder()
    assert embedder.embed([]) == []
    assert embedder.embed_single("") == [0.0] * 384


def test_similarity():
    embedder = get_embedder()
    v1 = [1.0] + [0.0] * 383
    v2 = [1.0] + [0.0] * 383
    v3 = [1.0] + [0.0] * 383  # same as v1
    assert abs(embedder.similarity(v1, v2) - 1.0) < 0.01
    assert abs(embedder.similarity(v1, v3) - 1.0) < 0.01
