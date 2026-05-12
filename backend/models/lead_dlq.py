"""
backend/models/lead_dlq.py — Lead Dead Letter Queue (DLQ) Model

DLQ tracks leads that failed processing with:
    - Failure reason and timestamp
    - Retry count with exponential backoff
    - Original lead data and metadata
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from backend.shared.db import Base


class LeadDLQStage(StrEnum):
    """DLQ queue stages."""
    new = "new"
    retrying = "retrying"
    failed_permanent = "failed_permanent"
    resolved = "resolved"


class LeadDLQ(Base):
    """
    LeadDLQ — Dead Letter Queue for failed lead processing.

    Tracks leads that failed during analysis, scoring, or persistence
    with automatic retry and exponential backoff.

    Attributes:
        id: UUID primary key
        original_lead_id: ID of the original lead (if exists)
        original_lead_data: Full lead data that failed
        failure_type: Category of failure (validation, api_error, database)
        error_message: Detailed error message
        retry_count: Number of retry attempts
        last_retry_at: Timestamp of last retry
        created_at: Record creation timestamp

    Usage:
        from backend.models.lead_dlq import LeadDLQ
        from backend.shared.db import get_db_session

        dlq_entry = LeadDLQ(
            original_lead_id=lead.id,
            failure_type="api_error",
            error_message=str(exc),
            retry_count=0,
        )
        async with get_db_session() as session:
            session.add(dlq_entry)
            await session.commit()
    """

    __tablename__ = "lead_dlq"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Reference to original lead (if exists)
    original_lead_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    # Original lead data (full copy for debugging)
    original_lead_data = Column(JSONB, nullable=False)

    # Failure information
    failure_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="Category: validation, api_error, database, rate_limit, timeout",
    )
    error_message = Column(Text, nullable=True)
    error_stack = Column(Text, nullable=True)

    # Retry tracking
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    last_retry_at = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    # Processing state
    stage = Column(
        String(32),
        nullable=False,
        default=LeadDLQStage.new,
        index=True,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(64), nullable=True)  # "manual", "auto_resolved", "retry_success"

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return (
            f"<LeadDLQ(id={self.id}, failure_type={self.failure_type}, "
            f"retry_count={self.retry_count})>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "original_lead_id": str(self.original_lead_id) if self.original_lead_id else None,
            "original_lead_data": self.original_lead_data,
            "failure_type": self.failure_type,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "stage": self.stage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def can_retry(self) -> bool:
        """Check if this DLQ entry can be retried."""
        return self.retry_count < self.max_retries and self.stage == LeadDLQStage.new

    def calculate_backoff(self) -> datetime:
        """Calculate next retry time with exponential backoff (base 2 hours)."""
        from datetime import timedelta
        backoff_minutes = 2 ** self.retry_count * 60  # 2h, 4h, 8h, etc.
        return datetime.utcnow() + timedelta(minutes=min(backoff_minutes, 2880))  # Max 48h
