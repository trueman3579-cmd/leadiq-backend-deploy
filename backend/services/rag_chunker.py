"""
rag_chunker.py — Document chunking service for RAG pipeline.

Implements recursive character text splitting with overlap,
based on LangChain's RecursiveCharacterTextSplitter pattern.

Research: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
(Lewis et al., NeurIPS 2020) — chunking is critical for retrieval quality.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class ChunkConfig:
    """Configuration for document chunking."""
    chunk_size: int = 500
    chunk_overlap: int = 50
    separators: List[str] = None

    def __post_init__(self):
        if self.separators is None:
            self.separators = ["\n\n", "\n", ". ", " ", ""]


class RAGChunker:
    """
    Chunk documents into overlapping segments for RAG indexing.

    Strategy:
        1. Split on semantic boundaries (paragraphs, sentences)
        2. Maintain overlap for context continuity
        3. Respect token limits (chunk_size)
    """

    def __init__(self, config: ChunkConfig | None = None):
        self.config = config or ChunkConfig()

    def chunk_text(self, text: str, metadata: dict | None = None) -> List[dict]:
        """
        Split text into chunks with metadata.

        Args:
            text: Raw document text
            metadata: Optional source metadata (URL, type, etc.)

        Returns:
            List of chunks with text and metadata
        """
        if not text or not text.strip():
            return []

        chunks = []
        separators = self.config.separators

        # Start with full text
        remaining = text.strip()

        while remaining:
            chunk_text, remaining = self._split_once(remaining, separators)
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text.strip(),
                    "metadata": metadata or {},
                    "char_count": len(chunk_text),
                })

        return chunks

    def _split_once(self, text: str, separators: List[str]) -> tuple[str, str]:
        """Split text at first suitable separator within chunk_size."""
        if len(text) <= self.config.chunk_size:
            return text, ""

        # Try each separator in order of preference
        for sep in separators:
            if not sep:
                # Final fallback: hard split at chunk_size
                split_point = self.config.chunk_size
                return text[:split_point], text[split_point:]

            # Find last occurrence of separator before chunk_size
            search_area = text[: self.config.chunk_size + len(sep)]
            last_idx = search_area.rfind(sep)

            if last_idx > 0:
                # Include separator in first chunk
                split_point = last_idx + len(sep)
                return text[:split_point], text[split_point:]

        # Hard fallback
        return text[: self.config.chunk_size], text[self.config.chunk_size :]

    def chunk_documents(
        self, documents: List[dict],
    ) -> List[dict]:
        """
        Chunk multiple documents.

        Args:
            documents: List of {"text": str, "metadata": dict}

        Returns:
            Flat list of all chunks
        """
        all_chunks = []
        for doc in documents:
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})
            chunks = self.chunk_text(text, metadata)
            all_chunks.extend(chunks)
        return all_chunks

    def chunk_with_overlap(self, text: str, metadata: dict | None = None) -> List[dict]:
        """
        Create overlapping chunks for better context continuity.

        Each chunk overlaps with the next by chunk_overlap characters.
        """
        if not text or not text.strip():
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.config.chunk_size
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "metadata": metadata or {},
                    "char_count": len(chunk_text),
                })

            # Move forward by chunk_size - overlap
            start += self.config.chunk_size - self.config.chunk_overlap

            # Prevent infinite loop on tiny texts
            if start <= 0:
                break

        return chunks


def create_scraper_chunker() -> RAGChunker:
    """Chunker optimized for web-scraped content."""
    return RAGChunker(
        config=ChunkConfig(
            chunk_size=400,
            chunk_overlap=40,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
    )


def create_news_chunker() -> RAGChunker:
    """Chunker optimized for news articles."""
    return RAGChunker(
        config=ChunkConfig(
            chunk_size=300,
            chunk_overlap=30,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
    )


def create_funding_chunker() -> RAGChunker:
    """Chunker optimized for funding announcements."""
    return RAGChunker(
        config=ChunkConfig(
            chunk_size=200,
            chunk_overlap=20,
            separators=["\n", ". ", " ", ""],
        )
    )
