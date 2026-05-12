"""
backend/models/icp.py — Ideal Customer Profile SQLAlchemy Model

Stores user-defined ICPs for lead matching and scoring.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from backend.shared.db import Base


class ICP(Base):
    """
    ICP — Ideal Customer Profile for lead matching.

    Attributes:
        id: UUID primary key
        name: Human-readable ICP name (e.g., "SaaS Startup Series A")
        description: Natural language description
        target_titles: Job titles to target (e.g., ["CTO", "VP Engineering"])
        target_industries: Industries to target (e.g., ["SaaS", "Fintech"])
        target_sizes: Company size ranges (e.g., ["11-50", "51-200"])
        target_locations: Locations to target (e.g., ["India", "USA"])
        target_stack: Tech stack to target (e.g., ["React", "Node.js"])
        funding_stages: Funding stages (e.g., ["seed", "series-a"])
        required_signals: Required intent signals (e.g., ["hiring"])
        min_confidence: Minimum lead confidence threshold
        embedding: 768-dim vector for semantic ICP matching
        created_at: Record creation timestamp
        updated_at: Record update timestamp
    """

    __tablename__ = "icps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Target criteria
    target_titles = Column(ARRAY(String), nullable=True, default=list)
    target_industries = Column(ARRAY(String), nullable=True, default=list)
    target_sizes = Column(ARRAY(String), nullable=True, default=list)
    target_locations = Column(ARRAY(String), nullable=True, default=list)
    target_stack = Column(ARRAY(String), nullable=True, default=list)
    funding_stages = Column(ARRAY(String), nullable=True, default=list)
    required_signals = Column(ARRAY(String), nullable=True, default=list)

    # Matching threshold
    min_confidence = Column(Float, nullable=False, default=0.65)

    # Embedding for semantic matching
    # Note: Will be TEXT if pgvector not installed
    try:
        from pgvector.sqlalchemy import Vector

        embedding = Column(Vector(768), nullable=True)
    except ImportError:
        embedding = Column(Text, nullable=True)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ICP(id={self.id}, name={self.name})>"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "target_titles": self.target_titles or [],
            "target_industries": self.target_industries or [],
            "target_sizes": self.target_sizes or [],
            "target_locations": self.target_locations or [],
            "target_stack": self.target_stack or [],
            "funding_stages": self.funding_stages or [],
            "required_signals": self.required_signals or [],
            "min_confidence": self.min_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_embedding_text(self) -> str:
        """
        Generate text for embedding.

        Combines all ICP criteria into a single text for vector embedding.
        """
        parts = []

        if self.target_titles:
            parts.append(" ".join(self.target_titles))
        if self.target_industries:
            parts.append(" ".join(self.target_industries))
        if self.target_stack:
            parts.append(" ".join(self.target_stack))
        if self.description:
            parts.append(self.description)

        return " ".join(parts)