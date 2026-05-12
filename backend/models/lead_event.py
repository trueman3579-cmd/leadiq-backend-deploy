"""
backend/models/lead_event.py — LeadEvent SQLAlchemy Model

Every user action on a lead is logged here = labeled training data.
This is the feedback flywheel for self-improving extraction quality.

Event Types:
    - approved: User approved the extracted lead
    - rejected: User rejected the lead
    - field_edited: User corrected a specific field
    - email_bounced: Email delivery failed
    - email_replied: Recipient responded to outreach
    - converted: Lead converted to customer
    - enriched: Lead enriched with additional data
    - signal_fired: Intent signal detected

Usage:
    event = LeadEvent(
        lead_id=lead.id,
        event_type="field_edited",
        field_name="email",
        original_value="john@example.com",
        corrected_value="john.doe@example.com",
        time_to_decision_ms=3500,
        source_actor="tracxn",
    )
    session.add(event)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.shared.db import Base


class LeadEventType(StrEnum):
    """Types of events that can occur on a lead."""

    approved = "approved"
    rejected = "rejected"
    field_edited = "field_edited"
    email_bounced = "email_bounced"
    email_replied = "email_replied"
    converted = "converted"
    enriched = "enriched"
    signal_fired = "signal_fired"


class LeadEvent(Base):
    """
    LeadEvent — Feedback flywheel for self-improving extraction.

    Every user action on a lead is logged here. This creates labeled
    training data for improving extraction quality over time.

    Attributes:
        id: UUID primary key
        lead_id: Foreign key to the Lead this event belongs to
        event_type: Type of event (approved, rejected, field_edited, etc.)
        field_name: Which field was edited (for field_edited events)
        original_value: What the LLM extracted
        corrected_value: What the human corrected it to
        time_to_decision_ms: How long before user acted (fast = confident)
        icp_id: Which ICP this lead matched (if any)
        source_actor: Which data source produced this lead
        created_at: When this event occurred

    Indexes:
        - ix_lead_events_type: For filtering by event type
        - ix_lead_events_source: For filtering by source actor
        - ix_lead_events_lead_id: For querying all events for a lead
    """

    __tablename__ = "lead_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(
        Enum(LeadEventType, name="lead_event_type"),
        nullable=False,
        index=True,
    )
    field_name = Column(String(255), nullable=True)  # Which field was edited
    original_value = Column(Text, nullable=True)  # What LLM extracted
    corrected_value = Column(Text, nullable=True)  # What human changed it to
    time_to_decision_ms = Column(Integer, nullable=True)  # Fast = confident
    icp_id = Column(UUID(as_uuid=True), ForeignKey("icps.id"), nullable=True)
    source_actor = Column(String(100), nullable=True, index=True)  # e.g., "tracxn"
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    # Relationship
    lead = relationship("Lead", back_populates="events")

    def __repr__(self) -> str:
        return f"<LeadEvent(id={self.id}, type={self.event_type}, lead_id={self.lead_id})>"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "lead_id": str(self.lead_id),
            "event_type": self.event_type.value,
            "field_name": self.field_name,
            "original_value": self.original_value,
            "corrected_value": self.corrected_value,
            "time_to_decision_ms": self.time_to_decision_ms,
            "icp_id": str(self.icp_id) if self.icp_id else None,
            "source_actor": self.source_actor,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Add this to the Lead model (in lead.py):
# events = relationship("LeadEvent", back_populates="lead", cascade="all, delete-orphan")