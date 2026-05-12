"""
backend/services/deduplication.py — Advanced Deduplication Service.

Multi-tier deduplication that ensures no duplicate leads enter the pipeline:

  Tier 1 (Primary): Content hash exact matching — fast, deterministic.
  Tier 2 (Secondary): pgvector cosine similarity (threshold 0.92) — catches
                       semantically similar company entries.

Returns a DedupResult with the unique leads, duplicate count, and stats.
"""
from __future__ import annotations

import hashlib
import json
import structlog
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.models import Lead
from backend.shared.stream import redis_stream

logger = structlog.get_logger(__name__)

# Similarity threshold for vector-based dedup (cosine distance < 0.08 = same entity)
VECTOR_SIMILARITY_THRESHOLD: float = 0.92

# Fields used to build the content hash for exact matching
HASH_FIELDS: list[str] = [
    "email",
    "linkedin_url",
    "company_domain",
    "company_name",
]


class DedupResult:
    """Result of a deduplication operation."""

    def __init__(
        self,
        unique_leads: list[dict[str, Any]],
        duplicate_count: int,
        stats: dict[str, Any],
    ) -> None:
        self.unique_leads = unique_leads
        self.duplicate_count = duplicate_count
        self.stats = stats

    def __repr__(self) -> str:
        return (
            f"DedupResult(unique={len(self.unique_leads)}, "
            f"duplicates={self.duplicate_count})"
        )


class DeduplicationService:
    """Service for deduplicating leads using content hash and vector similarity.

    Usage:
        service = DeduplicationService()
        result = await service.deduplicate(lead_dicts, session)
        unique = result.unique_leads
    """

    def __init__(self) -> None:
        self._stats: dict[str, Any] = {
            "total_input": 0,
            "exact_hash_matches": 0,
            "vector_similarity_matches": 0,
            "unique_output": 0,
        }

    # ── Public API ────────────────────────────────────────────────────────────────

    async def deduplicate(
        self,
        leads: list[dict[str, Any]],
        session: AsyncSession,
    ) -> DedupResult:
        """Deduplicate a batch of leads.

        Primary dedup: content hash exact matching (fast).
        Secondary dedup: vector similarity via pgvector (threshold 0.92).

        Args:
            leads: List of lead dictionaries to deduplicate
            session: Database session for checking existing leads

        Returns:
            DedupResult with unique leads, duplicate count, and stats
        """
        self._stats["total_input"] = len(leads)
        unique_leads: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        for lead in leads:
            # Tier 1: Check content hash against in-memory set (batch)
            content_hash = self._compute_content_hash(lead)

            if content_hash in seen_hashes:
                self._stats["exact_hash_matches"] += 1
                logger.debug("dedup_batch_hash_match", hash=content_hash)
                continue

            # Tier 1: Check content hash against database
            existing_by_hash = await self._check_hash_in_db(content_hash, session)
            if existing_by_hash:
                self._stats["exact_hash_matches"] += 1
                logger.debug("dedup_db_hash_match", hash=content_hash)
                continue

            # Tier 2: Check vector similarity (if embedding available)
            embedding = lead.get("embedding")
            if embedding:
                existing_by_vector = await self._check_vector_similarity(
                    embedding, session
                )
                if existing_by_vector:
                    self._stats["vector_similarity_matches"] += 1
                    logger.debug("dedup_vector_match", threshold=VECTOR_SIMILARITY_THRESHOLD)
                    continue

            # No duplicates found — keep this lead
            seen_hashes.add(content_hash)
            unique_leads.append(lead)

        self._stats["unique_output"] = len(unique_leads)
        duplicate_count = len(leads) - len(unique_leads)

        logger.info(
            "dedup_complete",
            total_input=self._stats["total_input"],
            unique=self._stats["unique_output"],
            hash_matches=self._stats["exact_hash_matches"],
            vector_matches=self._stats["vector_similarity_matches"],
        )

        return DedupResult(
            unique_leads=unique_leads,
            duplicate_count=duplicate_count,
            stats=dict(self._stats),
        )

    async def check_duplicate(
        self,
        new_lead: dict[str, Any],
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Check a single new lead against existing leads in the database.

        Args:
            new_lead: Lead dictionary to check
            session: Database session

        Returns:
            Dict with is_duplicate flag, match_type, and optional existing_lead_id
        """
        content_hash = self._compute_content_hash(new_lead)

        # Tier 1: Content hash exact match
        existing = await self._check_hash_in_db(content_hash, session)
        if existing:
            return {
                "is_duplicate": True,
                "match_type": "exact_hash",
                "existing_lead_id": str(existing.id),
                "confidence": 1.0,
            }

        # Tier 2: Vector similarity
        embedding = new_lead.get("embedding")
        if embedding:
            existing = await self._check_vector_similarity(embedding, session)
            if existing:
                return {
                    "is_duplicate": True,
                    "match_type": "vector_similarity",
                    "existing_lead_id": str(existing.id),
                    "confidence": VECTOR_SIMILARITY_THRESHOLD,
                }

        return {
            "is_duplicate": False,
            "match_type": None,
            "existing_lead_id": None,
            "confidence": 0.0,
        }

    # ── Tier 1: Content Hash ───────────────────────────────────────────────────────

    def _compute_content_hash(self, lead: dict[str, Any]) -> str:
        """Compute a deterministic content hash from key identifying fields.

        Uses SHA-256 of concatenated normalized field values.
        Only fields present in HASH_FIELDS are included.

        Args:
            lead: Lead dictionary

        Returns:
            SHA-256 hex digest string
        """
        hash_input_parts: list[str] = []

        for field in HASH_FIELDS:
            value = lead.get(field)
            if value:
                # Normalize: lowercase, strip whitespace
                normalized = str(value).lower().strip()
                hash_input_parts.append(normalized)

        # If no hashable fields, hash the entire lead JSON
        if not hash_input_parts:
            hash_input = json.dumps(lead, sort_keys=True, default=str)
        else:
            hash_input = "|".join(hash_input_parts)

        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    async def _check_hash_in_db(
        self,
        content_hash: str,
        session: AsyncSession,
    ) -> Lead | None:
        """Check if a content hash already exists in the database.

        Args:
            content_hash: SHA-256 hash string
            session: Database session

        Returns:
            Existing Lead if found, None otherwise
        """
        try:
            result = await session.execute(
                select(Lead)
                .where(Lead.content_hash == content_hash)
                .limit(1)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            logger.error("dedup_hash_db_check_failed", error=str(exc))
            return None

    # ── Tier 2: Vector Similarity ──────────────────────────────────────────────────

    async def _check_vector_similarity(
        self,
        embedding: list[float],
        session: AsyncSession,
    ) -> Lead | None:
        """Check if a lead with similar embedding exists using pgvector.

        Uses cosine distance with threshold VECTOR_SIMILARITY_THRESHOLD.

        Args:
            embedding: Float vector embedding (768-dim for text-embedding-004)
            session: Database session

        Returns:
            Existing Lead if vector match found, None otherwise
        """
        try:
            from pgvector.sqlalchemy import Vector

            # Cosine distance threshold: 0.08 corresponds to ~0.92 similarity
            distance_threshold = 1.0 - VECTOR_SIMILARITY_THRESHOLD

            result = await session.execute(
                select(Lead)
                .where(Lead.embedding.isnot(None))
                .order_by(Lead.embedding.cosine_distance(embedding))
                .limit(1)
            )
            candidate = result.scalar_one_or_none()

            if candidate and candidate.embedding is not None:
                # Compute distance directly using the database
                dist_result = await session.execute(
                    select(Lead.embedding.cosine_distance(embedding))
                    .where(Lead.id == candidate.id)
                )
                distance = dist_result.scalar()

                if distance is not None and distance < distance_threshold:
                    logger.debug(
                        "dedup_vector_candidate",
                        lead_id=str(candidate.id),
                        distance=round(distance, 4),
                    )
                    return candidate

            return None

        except ImportError:
            logger.warning("pgvector_not_available_skipping_vector_dedup")
            return None
        except AttributeError:
            logger.warning("cosine_distance_not_available_skipping_vector_dedup")
            return None
        except Exception as exc:
            logger.error("dedup_vector_check_failed", error=str(exc))
            return None
