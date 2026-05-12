"""
rag_indexer.py — Store chunks in pgvector for RAG retrieval.

Uses PostgreSQL + pgvector extension with HNSW index for fast
approximate nearest neighbor search.

Research: "The Faiss library" (Douze et al., 2024) — HNSW indexing
for 150x faster vector search. Implemented via pgvector in PostgreSQL.
"""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


class RAGIndexer:
    """
    Index document chunks in pgvector for similarity search.

    Schema:
        company_context (id, company_id, chunk_text, embedding vector(384),
                        source_type, source_url, trust_score, created_at)
    """

    def __init__(self):
        self.dimension = 384  # all-MiniLM-L6-v2

    async def init_schema(self) -> None:
        """Ensure pgvector extension and table exist."""
        async with AsyncSessionLocal() as session:
            # Enable pgvector
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

            # Create table if not exists
            await session.execute(text(f"""
                CREATE TABLE IF NOT EXISTS company_context (
                    id SERIAL PRIMARY KEY,
                    company_id VARCHAR(255) NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding vector({self.dimension}),
                    source_type VARCHAR(50),
                    source_url VARCHAR(500),
                    trust_score FLOAT DEFAULT 5.0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))

            # Create HNSW index for fast similarity search
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_company_context_embedding
                ON company_context USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """))

            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_company_context_company
                ON company_context(company_id)
            """))

            await session.commit()
            logger.info("RAG schema initialized: company_context + HNSW index")

    async def index_chunks(
        self,
        company_id: str,
        chunks: List[dict],
        source_type: str = "website",
        source_url: str = "",
        trust_score: float = 5.0,
    ) -> int:
        """
        Store chunks with embeddings in pgvector.

        Args:
            company_id: Unique company identifier
            chunks: List of {"text": str, "embedding": List[float]}
            source_type: website, news, crunchbase, linkedin, etc.
            source_url: Original source URL
            trust_score: URL trust score (0-10)

        Returns:
            Number of chunks indexed
        """
        if not chunks:
            return 0

        async with AsyncSessionLocal() as session:
            for chunk in chunks:
                embedding = chunk.get("embedding")
                if not embedding or len(embedding) != self.dimension:
                    logger.warning(f"Invalid embedding for chunk, skipping")
                    continue

                await session.execute(
                    text("""
                        INSERT INTO company_context
                        (company_id, chunk_text, embedding, source_type, source_url, trust_score)
                        VALUES (:company_id, :chunk_text, :embedding, :source_type, :source_url, :trust_score)
                    """),
                    {
                        "company_id": company_id,
                        "chunk_text": chunk["text"][:2000],  # Limit text length
                        "embedding": str(embedding),  # pgvector accepts array string
                        "source_type": source_type,
                        "source_url": source_url[:500],
                        "trust_score": trust_score,
                    },
                )

            await session.commit()
            logger.info(f"Indexed {len(chunks)} chunks for company={company_id}")
            return len(chunks)

    async def delete_company_context(self, company_id: str) -> int:
        """Remove all context for a company (for re-indexing)."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("DELETE FROM company_context WHERE company_id = :company_id"),
                {"company_id": company_id},
            )
            await session.commit()
            deleted = result.rowcount
            logger.info(f"Deleted {deleted} chunks for company={company_id}")
            return deleted

    async def get_stats(self) -> dict:
        """Get indexing statistics."""
        async with AsyncSessionLocal() as session:
            total = await session.execute(text("SELECT COUNT(*) FROM company_context"))
            companies = await session.execute(
                text("SELECT COUNT(DISTINCT company_id) FROM company_context")
            )
            sources = await session.execute(
                text("SELECT source_type, COUNT(*) FROM company_context GROUP BY source_type")
            )

            return {
                "total_chunks": total.scalar(),
                "total_companies": companies.scalar(),
                "source_distribution": {row[0]: row[1] for row in sources.fetchall()},
            }
