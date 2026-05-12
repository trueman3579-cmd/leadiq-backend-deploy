"""
rag_embedder.py — Embedding service for RAG pipeline.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim) for fast,
high-quality sentence embeddings.

Research: "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks"
(Reimers & Gurevych, EMNLP 2019) — 22.7M params, 253M downloads/month.
"""

from __future__ import annotations

import os
from typing import List

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Lazy-load model to avoid startup penalty
_model = None


def _get_model():
    """Lazy initialization of sentence transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        _model = SentenceTransformer(model_name, device="cpu")
    return _model


class RAGEmbedder:
    """
    Convert text chunks to embedding vectors.

    Model: all-MiniLM-L6-v2 (production) or numpy hash-based fallback (dev).
    - Dimensions: 384
    - Parameters: 22.7M
    - Speed: ~50ms per chunk (CPU), ~10ms (GPU)
    - Accuracy: 94% retrieval accuracy on MSMARCO
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self._model = None
        self._fallback = False
        # Pre-seeded random projection matrix for lightweight fallback
        np.random.seed(42)
        self._projection = np.random.randn(10000, 384).astype(np.float32)
        self._projection /= np.linalg.norm(self._projection, axis=1, keepdims=True)

    @property
    def model(self):
        """Lazy-load model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name, device="cpu")
                self._fallback = False
            except ImportError:
                logger.warning("sentence_transformers not available, using hash-based fallback embeddings")
                self._fallback = True
                self._model = "fallback"
        return self._model

    def _hash_embed(self, text: str) -> np.ndarray:
        """Fast hash-based embedding fallback (no ML required)."""
        # Simple character n-gram frequency vector projected to 384-dim
        text = text.lower().strip()
        if not text:
            return np.zeros(384, dtype=np.float32)

        # Character trigram frequencies
        indices = []
        weights = []
        for i in range(len(text) - 2):
            tri = text[i:i+3]
            idx = hash(tri) % 10000
            indices.append(idx)
            weights.append(1.0)

        if not indices:
            return np.zeros(384, dtype=np.float32)

        # Sparse vector
        sparse = np.zeros(10000, dtype=np.float32)
        for idx, w in zip(indices, weights):
            sparse[idx] += w

        # Normalize
        norm = np.linalg.norm(sparse)
        if norm > 0:
            sparse = sparse / norm

        # Project to 384-dim
        embedding = sparse @ self._projection
        embedding /= (np.linalg.norm(embedding) + 1e-8)
        return embedding.astype(np.float32)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts.

        Args:
            texts: List of text strings

        Returns:
            List of 384-dimensional embedding vectors
        """
        if not texts:
            return []

        # Filter empty strings
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return []

        self.model  # Ensure loaded
        if self._fallback:
            embeddings = np.stack([self._hash_embed(t) for t in valid_texts])
        else:
            embeddings = self._model.encode(valid_texts, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_single(self, text: str) -> List[float]:
        """Embed a single text."""
        if not text or not text.strip():
            return [0.0] * 384

        self.model  # Ensure loaded
        if self._fallback:
            embedding = self._hash_embed(text)
        else:
            embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_chunks(self, chunks: List[dict]) -> List[dict]:
        """
        Embed a list of chunks and attach embeddings.

        Args:
            chunks: List of {"text": str, "metadata": dict}

        Returns:
            Chunks with "embedding" field added
        """
        texts = [c["text"] for c in chunks]
        embeddings = self.embed(texts)

        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding

        return chunks

    def similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        dot = np.dot(v1, v2)
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        if norm == 0:
            return 0.0
        return float(min(1.0, max(-1.0, dot / norm)))

    def get_dimension(self) -> int:
        """Return embedding dimension."""
        return 384


# Singleton for reuse
_embedder = None


def get_embedder() -> RAGEmbedder:
    """Get singleton embedder instance."""
    global _embedder
    if _embedder is None:
        _embedder = RAGEmbedder()
    return _embedder
