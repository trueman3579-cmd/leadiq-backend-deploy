"""
backend/services/dedup_service.py — 3-Tier Deduplication Engine

Implements a multi-tier deduplication strategy:
    Tier 1: Exact match (fast, free) — email, linkedin_url, company_domain
    Tier 2: Fuzzy match (medium) — company name with typos, similar emails
    Tier 3: Vector similarity (slow) — pgvector embeddings, cosine distance

Usage:
    from backend.services.dedup_service import find_duplicate, merge_leads

    existing = await find_duplicate(new_lead, session)
    if existing:
        merged = await merge_leads(existing, new_lead)
"""
from __future__ import annotations

import structlog
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.models import Lead
from backend.services.confidence import SOURCE_TRUST

logger = structlog.get_logger()


# ── Tier 1: Exact Match ─────────────────────────────────────────────────────────

async def find_exact_match(lead: dict[str, Any], session: AsyncSession) -> Lead | None:
    """
    Tier 1: Check for exact matches on unique identifiers.

    Checks:
        1. Email address (most specific)
        2. LinkedIn URL (identity anchor)
        3. Company domain + title combination

    Returns:
        Lead if exact match found, None otherwise
    """
    # Check by email
    if lead.get("email"):
        result = await session.execute(
            select(Lead).where(Lead.email == lead["email"]).limit(1)
        )
        if match := result.scalar():
            logger.debug("dedup_exact_email", lead_id=str(match.id), email=lead["email"])
            return match

    # Check by LinkedIn URL
    if lead.get("linkedin_url"):
        result = await session.execute(
            select(Lead).where(Lead.linkedin_url == lead["linkedin_url"]).limit(1)
        )
        if match := result.scalar():
            logger.debug("dedup_exact_linkedin", lead_id=str(match.id))
            return match

    # Check by company domain + title
    if lead.get("company_domain") and lead.get("title"):
        result = await session.execute(
            select(Lead).where(
                Lead.company_domain == lead["company_domain"],
                Lead.title == lead["title"],
            ).limit(1)
        )
        if match := result.scalar():
            logger.debug("dedup_exact_domain_title", lead_id=str(match.id))
            return match

    return None


# ── Tier 2: Fuzzy Match ──────────────────────────────────────────────────────────

def similarity_score(a: str, b: str) -> float:
    """Calculate string similarity using SequenceMatcher."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).quick_ratio()


async def find_fuzzy_match(lead: dict[str, Any], session: AsyncSession) -> Lead | None:
    """
    Tier 2: Check for fuzzy matches on company names.

    Uses Levenshtein-like similarity for:
        - Company names with typos
        - Similar email domains
        - Partial URL matches

    Threshold: similarity > 0.85 for match

    Optimized with:
        1. Pre-filter by industry (if available)
        2. Pre-filter by location (if available)
        3. Paginated query to avoid N+1 and memory issues

    Returns:
        Lead if fuzzy match found, None otherwise
    """
    company_name = lead.get("company_name", "")
    if not company_name:
        return None

    lead_industry = lead.get("industry")
    lead_location = lead.get("location")

    # Build query with optional filters to narrow candidates
    stmt = select(Lead).where(Lead.company_name.isnot(None))

    # Filter by industry first if available (reduces candidate set significantly)
    if lead_industry:
        stmt = stmt.where(Lead.industry == lead_industry)

    # Get candidates with pagination to avoid N+1 query issues
    # Process in small batches to keep memory usage low
    batch_size = 50
    offset = 0

    while True:
        batch_stmt = stmt.offset(offset).limit(batch_size)
        result = await session.execute(batch_stmt)
        candidates = result.scalars().all()

        if not candidates:
            break

        for candidate in candidates:
            sim = similarity_score(company_name, candidate.company_name or "")
            if sim > 0.85:
                # Additional check: same industry or location
                same_industry = lead_industry is None or lead_industry == candidate.industry
                same_location = lead_location is None or lead_location == candidate.location

                if same_industry or same_location:
                    logger.debug(
                        "dedup_fuzzy_match",
                        candidate_id=str(candidate.id),
                        similarity=sim,
                    )
                    return candidate

        offset += batch_size

        # Safety limit: max 2000 candidates to check
        if offset >= 2000:
            break

    return None


# ── Tier 3: Vector Similarity ────────────────────────────────────────────────────

async def find_vector_match(
    lead: dict[str, Any],
    session: AsyncSession,
    embedding: list[float] | None = None,
) -> Lead | None:
    """
    Tier 3: Check for semantic similarity using pgvector.

    Uses cosine distance on embeddings:
        - distance < 0.12 = same company (empirical threshold)
        - distance < 0.20 = same industry

    Args:
        lead: Lead dictionary
        session: Database session
        embedding: Pre-computed embedding (optional)

    Returns:
        Lead if vector match found, None otherwise
    """
    # Skip if no embedding provided
    if embedding is None:
        return None

    try:
        # Use pgvector cosine distance
        # Note: Requires pgvector extension installed

        # Find similar leads by embedding
        result = await session.execute(
            select(Lead, Lead.embedding.cosine_distance(embedding).label("dist"))
            .where(Lead.id != lead.get("id"))  # Exclude self
            .where(Lead.embedding.isnot(None))
            .order_by("dist")
            .limit(10)
        )

        for row in result:
            candidate, distance = row
            if distance < 0.12:  # Empirical threshold for same company
                logger.debug(
                    "dedup_vector_match",
                    candidate_id=str(candidate.id),
                    distance=distance,
                )
                return candidate

        return None

    except ImportError:
        logger.warning("pgvector_not_installed_skipping_vector_dedup")
        return None


# ── Main Dedup Function ──────────────────────────────────────────────────────────

async def find_duplicate(
    lead: dict[str, Any],
    session: AsyncSession,
    embedding: list[float] | None = None,
) -> Lead | None:
    """
    Find duplicate lead using 3-tier strategy.

    Execution order:
        1. Exact match (instant, free)
        2. Fuzzy match (medium speed)
        3. Vector similarity (slow, requires embedding)

    Args:
        lead: Lead dictionary to check
        session: Database session
        embedding: Pre-computed embedding for Tier 3 (optional)

    Returns:
        Existing Lead if duplicate found, None otherwise
    """
    # Tier 1: Exact match (fastest)
    if match := await find_exact_match(lead, session):
        return match

    # Tier 2: Fuzzy match (medium)
    if match := await find_fuzzy_match(lead, session):
        return match

    # Tier 3: Vector similarity (slowest)
    if embedding:
        if match := await find_vector_match(lead, session, embedding):
            return match

    return None


# ── Merge Function ─────────────────────────────────────────────────────────────

async def merge_leads(
    existing: Lead,
    incoming: dict[str, Any],
    session: AsyncSession,
) -> Lead:
    """
    Merge incoming lead data into existing lead.

    Strategy: Keep highest-confidence field values.
    Never overwrite with lower-quality data.

    Args:
        existing: Existing Lead model instance
        incoming: Incoming lead dictionary
        session: Database session

    Returns:
        Updated Lead instance (not yet committed)
    """
    existing_trust = SOURCE_TRUST.get(existing.source, 0.40)
    incoming_trust = SOURCE_TRUST.get(incoming.get("source", ""), 0.40)

    # Fields to potentially update
    updatable_fields = [
        "company_name",
        "industry",
        "location",
        "company_size",
        "funding_stage",
        "tech_stack",
        "email",
        "linkedin_url",
        "website",
        "founded_year",
        "title",
        "intent_signals",
    ]

    for field in updatable_fields:
        incoming_value = incoming.get(field)
        existing_value = getattr(existing, field, None)

        # Skip if incoming is empty
        if not incoming_value:
            continue

        # Update if:
        # 1. Existing is empty, OR
        # 2. Incoming source is more trusted
        if not existing_value or incoming_trust > existing_trust:
            setattr(existing, field, incoming_value)
            logger.debug(
                "merge_field_update",
                lead_id=str(existing.id),
                field=field,
                old_value=existing_value,
                new_value=incoming_value,
            )

    # Update confidence based on merged data
    from backend.services.confidence import compute_confidence

    existing.confidence = compute_confidence(
        {field: getattr(existing, field) for field in updatable_fields},
        existing.source,
    )

    # Update source URLs (keep both)
    if incoming.get("source_url"):
        existing_urls = existing.source_url or ""
        if incoming["source_url"] not in existing_urls:
            existing.source_url = f"{existing_urls};{incoming['source_url']}".strip(";")

    return existing