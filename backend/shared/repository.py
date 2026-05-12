"""
shared/repository.py — Data-access layer (Repository pattern).
All DB queries are here. Workers and routes must NOT touch SQLAlchemy directly.

Classes:
  PostRepo     — create / get / exists by hash
  LeadRepo     — upsert / list / update stage
  FeedbackRepo — create / list by lead
  QuotaRepo    — increment / get daily total
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.shared.models import Feedback, GovScheme, FundingEvent, JobSignal, Lead, Post, QuotaUsage, UserProfile


# ── PostRepo ──────────────────────────────────────────────────────────────────

class PostRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def exists_by_hash(self, content_hash: str) -> bool:
        result = await self._s.execute(
            select(Post.id).where(Post.content_hash == content_hash).limit(1)
        )
        return result.scalar() is not None

    async def get_by_hash(self, content_hash: str) -> Post | None:
        """Get post by content hash, or None if not found."""
        result = await self._s.execute(
            select(Post)
            .options(selectinload(Post.lead))
            .where(Post.content_hash == content_hash)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, data: dict[str, Any]) -> Post:
        post = Post(**data)
        self._s.add(post)
        await self._s.flush()
        return post

    async def get(self, post_id: str) -> Post | None:
        result = await self._s.execute(select(Post).where(Post.id == post_id))
        return result.scalar_one_or_none()


# ── LeadRepo ──────────────────────────────────────────────────────────────────

class LeadRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, data: dict[str, Any]) -> Lead:
        """Insert or update lead by post_id. Returns the persisted Lead."""
        if data.get("post_id") is None:
            lead = Lead(**data)
            self._s.add(lead)
            await self._s.flush()
            return lead
        stmt = (
            pg_insert(Lead)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["post_id"],
                set_={k: v for k, v in data.items() if k != "post_id"},
            )
            .returning(Lead)
        )
        result = await self._s.execute(stmt)
        lead = result.scalar_one()
        await self._s.flush()
        return lead

    async def get(self, lead_id: str) -> Lead | None:
        result = await self._s.execute(select(Lead).where(Lead.id == lead_id))
        return result.scalar_one_or_none()

    async def list_all(
        self,
        stage: str | None = None,
        min_score: float = 0.0,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Lead]:
        q = (
            select(Lead)
            .options(selectinload(Lead.post))
            .where(Lead.final_score >= min_score)
        )
        if stage:
            q = q.where(Lead.stage == stage)
        q = q.order_by(Lead.final_score.desc()).limit(limit).offset(offset)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_stale_signals(self, limit: int = 10) -> list[Lead]:
        """
        Get leads with stale intent signals for refresh.

        Companies are stale if:
            - No signal update in 24 hours
            - Last signal decayed below 0.5

        Args:
            limit: Maximum number of leads to return

        Returns:
            List of leads needing signal refresh
        """
        # Check if intent_signals has stale data (older than 24 hours)
        cutoff = datetime.now(UTC) - timedelta(hours=24)

        q = (
            select(Lead)
            .where(Lead.updated_at < cutoff)
            .order_by(Lead.updated_at.asc())
            .limit(limit)
        )
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def update_fields(self, lead_id: str, updates: dict[str, Any]) -> Lead | None:
        updates["updated_at"] = datetime.now(UTC)
        await self._s.execute(
            update(Lead).where(Lead.id == lead_id).values(**updates)
        )
        await self._s.flush()
        return await self.get(lead_id)


# ── FeedbackRepo ──────────────────────────────────────────────────────────────

class FeedbackRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, lead_id: str, rating: int, label: str | None = None, reviewer: str | None = None) -> Feedback:
        fb = Feedback(lead_id=lead_id, rating=rating, label=label, reviewer=reviewer)
        self._s.add(fb)
        await self._s.flush()
        return fb

    async def list_by_lead(self, lead_id: str) -> list[Feedback]:
        result = await self._s.execute(
            select(Feedback).where(Feedback.lead_id == lead_id).order_by(Feedback.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_recent_stats(self, days: int = 7) -> dict:
        """Aggregate feedback stats for recent window: avg rating, email validity, label distribution."""
        from datetime import date, timedelta

        cutoff = date.today() - timedelta(days=days)
        result = await self._s.execute(
            select(Feedback).where(Feedback.created_at >= cutoff)
        )
        feedbacks = list(result.scalars().all())

        if not feedbacks:
            return {
                "total_feedbacks": 0,
                "avg_rating": None,
                "rating_distribution": {},
                "label_distribution": {},
                "email_validity_pct": None,
            }

        total = len(feedbacks)
        avg_rating = sum(f.rating for f in feedbacks) / total
        rating_dist: dict[int, int] = {}
        label_dist: dict[str, int] = {}
        valid_emails = 0

        for f in feedbacks:
            rating_dist[f.rating] = rating_dist.get(f.rating, 0) + 1
            if f.label:
                label_dist[f.label] = label_dist.get(f.label, 0) + 1

        # Email validity: "good" labels as proxy for valid emails
        valid_emails = label_dist.get("good", 0) + label_dist.get("valid", 0)
        email_validity_pct = round(valid_emails / total * 100, 1) if total > 0 else None

        return {
            "total_feedbacks": total,
            "avg_rating": round(avg_rating, 2),
            "rating_distribution": rating_dist,
            "label_distribution": label_dist,
            "email_validity_pct": email_validity_pct,
        }


# ── QuotaRepo ─────────────────────────────────────────────────────────────────

class QuotaRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def increment(self, model: str, tokens: int, requests: int = 1) -> QuotaUsage:
        today = date.today().isoformat()
        stmt = (
            pg_insert(QuotaUsage)
            .values(date=today, model=model, tokens_used=tokens, requests_count=requests)
            .on_conflict_do_update(
                constraint="uq_quota_date_model",
                set_={
                    "tokens_used": QuotaUsage.tokens_used + tokens,
                    "requests_count": QuotaUsage.requests_count + requests,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(QuotaUsage)
        )
        result = await self._s.execute(stmt)
        usage = result.scalar_one()
        await self._s.flush()
        return usage

    async def get_daily_total(self, model: str, day: str | None = None) -> QuotaUsage | None:
        target = day or date.today().isoformat()
        result = await self._s.execute(
            select(QuotaUsage).where(QuotaUsage.date == target, QuotaUsage.model == model)
        )
        return result.scalar_one_or_none()


# ── ProfileRepo ───────────────────────────────────────────────────────────────

class ProfileRepo:
    """
    Singleton UserProfile repository (always id=1).
    Handles upsert, retrieval, and feedback-weights update.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active(self) -> UserProfile | None:
        """Return the singleton profile (id=1), or None if not yet created."""
        result = await self._s.execute(
            select(UserProfile).where(UserProfile.id == 1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, data: dict[str, Any]) -> UserProfile:
        """Create or fully replace the singleton profile."""
        data.pop("id", None)               # ensure id is not in data dict
        data["updated_at"] = datetime.now(UTC)
        stmt = (
            pg_insert(UserProfile)
            .values(id=1, **data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in data.items()},
            )
            .returning(UserProfile)
        )
        result = await self._s.execute(stmt)
        profile = result.scalar_one()
        await self._s.flush()
        return profile

    async def update_feedback_adjustments(
        self, adjustments: dict[str, float]
    ) -> None:
        """Persist updated feedback learning weights without touching other fields."""
        await self._s.execute(
            update(UserProfile)
            .where(UserProfile.id == 1)
            .values(feedback_adjustments=adjustments, updated_at=datetime.now(UTC))
        )
        await self._s.flush()


# ── GovSchemeRepo ────────────────────────────────────────────────────────────

class GovSchemeRepo:
    """Repository for GovScheme table — government scheme data."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, data: dict[str, Any]) -> GovScheme:
        stmt = (
            pg_insert(GovScheme)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["name", "department"],
                set_={k: v for k, v in data.items() if k not in ("name", "department")},
            )
            .returning(GovScheme)
        )
        result = await self._s.execute(stmt)
        scheme = result.scalar_one()
        await self._s.flush()
        return scheme

    async def list_all(self, department: str | None = None, min_trust: float = 0.0, limit: int = 200, offset: int = 0) -> list[GovScheme]:
        q = select(GovScheme).where(GovScheme.trust_score >= min_trust)
        if department:
            q = q.where(GovScheme.department.ilike(f"%{department}%"))
        q = q.order_by(GovScheme.collected_at.desc()).limit(limit).offset(offset)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def count(self, department: str | None = None) -> int:
        q = select(GovScheme)
        if department:
            q = q.where(GovScheme.department.ilike(f"%{department}%"))
        result = await self._s.execute(select(func.count()).select_from(q.subquery()))
        return result.scalar() or 0

    async def exists_by_name(self, name: str) -> bool:
        result = await self._s.execute(
            select(GovScheme.id).where(GovScheme.name == name).limit(1)
        )
        return result.scalar() is not None

    async def get_departments(self) -> list[str]:
        result = await self._s.execute(
            select(GovScheme.department).distinct().order_by(GovScheme.department)
        )
        return [row[0] for row in result]


# ── FundingEventRepo ─────────────────────────────────────────────────────────

class FundingEventRepo:
    """Repository for FundingEvent table — funding round signals."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, data: dict[str, Any]) -> FundingEvent:
        stmt = (
            pg_insert(FundingEvent)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["company_name", "amount", "round_type"],
                set_={k: v for k, v in data.items() if k not in ("company_name", "amount", "round_type")},
            )
            .returning(FundingEvent)
        )
        result = await self._s.execute(stmt)
        event = result.scalar_one()
        await self._s.flush()
        return event

    async def list_all(
        self,
        source: str | None = None,
        industry: str | None = None,
        min_trust: float = 0.0,
        limit: int = 200,
        offset: int = 0,
    ) -> list[FundingEvent]:
        q = select(FundingEvent).where(FundingEvent.trust_score >= min_trust)
        if source:
            q = q.where(FundingEvent.source == source)
        if industry:
            q = q.where(FundingEvent.industry.ilike(f"%{industry}%"))
        q = q.order_by(FundingEvent.date.desc().nullslast()).limit(limit).offset(offset)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._s.execute(select(func.count(FundingEvent.id)))
        return result.scalar() or 0

    async def get_stats(self) -> dict[str, Any]:
        total = await self.count()
        verified = await self._s.execute(
            select(func.count(FundingEvent.id)).where(FundingEvent.is_verified.is_(True))
        )
        sources = await self._s.execute(
            select(FundingEvent.source).distinct()
        )
        return {
            "total": total,
            "verified": verified.scalar() or 0,
            "sources": [row[0] for row in sources],
        }

    async def get_recent(self, hours: int = 24, limit: int = 50) -> list[FundingEvent]:
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        q = (
            select(FundingEvent)
            .where(FundingEvent.collected_at >= cutoff)
            .order_by(FundingEvent.date.desc().nullslast())
            .limit(limit)
        )
        result = await self._s.execute(q)
        return list(result.scalars().all())


# ── JobSignalRepo ────────────────────────────────────────────────────────────

class JobSignalRepo:
    """Repository for JobSignal table — hiring signals."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, data: dict[str, Any]) -> JobSignal:
        stmt = (
            pg_insert(JobSignal)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["company_name", "title", "source"],
                set_={k: v for k, v in data.items() if k not in ("company_name", "title", "source")},
            )
            .returning(JobSignal)
        )
        result = await self._s.execute(stmt)
        signal = result.scalar_one()
        await self._s.flush()
        return signal

    async def list_all(
        self,
        source: str | None = None,
        company: str | None = None,
        work_mode: str | None = None,
        min_velocity: int = 0,
        limit: int = 200,
        offset: int = 0,
    ) -> list[JobSignal]:
        q = select(JobSignal)
        if source:
            q = q.where(JobSignal.source == source)
        if company:
            q = q.where(JobSignal.company_name.ilike(f"%{company}%"))
        if work_mode:
            q = q.where(JobSignal.work_mode == work_mode)
        if min_velocity:
            q = q.where(JobSignal.hiring_velocity >= min_velocity)
        q = q.order_by(JobSignal.collected_at.desc()).limit(limit).offset(offset)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._s.execute(select(func.count(JobSignal.id)))
        return result.scalar() or 0

    async def get_stats(self) -> dict[str, Any]:
        total = await self.count()
        companies_result = await self._s.execute(
            select(JobSignal.company_name).distinct()
        )
        sources_result = await self._s.execute(
            select(JobSignal.source).distinct()
        )
        hot = await self._s.execute(
            select(func.count(JobSignal.id)).where(JobSignal.hiring_velocity >= 70)
        )
        return {
            "total": total,
            "companies": len([r[0] for r in companies_result]),
            "sources": [r[0] for r in sources_result],
            "hot_hiring": hot.scalar() or 0,
        }
