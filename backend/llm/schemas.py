"""
backend/llm/schemas.py — Pydantic v2 schemas for LLM analysis output.

This module defines Pydantic models for validating Gemini LLM extraction results.
The `AnalyzedLead` model enforces Colvin's validator logic for extraction quality.

Architecture:
- AnalyzedLead: Pydantic v2 model with 12 fields + validators (NEW, replaces dataclass)
- AnalysisResult: Original dataclass (kept for backward compatibility in analyzer.py)

Note: We use `AnalyzedLead` (not AnalysisResult) to avoid conflict with the
existing dataclass in backend/workers/analyzer.py.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AnalyzedLead(BaseModel):
    """
    Pydantic v2 model for LLM analysis output validation.

    Enforces Colvin's validator logic:
    - Rule 1: Confidence >0.7 requires evidence (company_name or contact_name)
    - Rule 2: is_opportunity=True AND confidence<0.35 → set is_opportunity=False
    - Rule 3: Intent and urgency must be from known values

    Config:
    - extra="ignore": Reject unknown fields (prevent hallucination injection)
    - from_attributes=True: Allow creation from ORM objects
    """

    # ── Classification fields (from classifier) ───────────────────────────────
    is_opportunity: bool = Field(
        default=False,
        description="True if genuine B2B buying/evaluation signal",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Model confidence 0.0-1.0",
    )
    intent: str = Field(
        default="other",
        description="buy | evaluate | pain | compare | other | hiring_urgent | hiring_planned | company_growth",
    )
    urgency: str = Field(
        default="low",
        description="high | medium | low",
    )
    reason: str = Field(
        default="",
        description="One-sentence explanation for classification",
    )

    # ── Enrichment fields (populated only when is_opportunity=True) ─────────────
    company_name: str | None = Field(
        default=None,
        description="Inferred company name",
    )
    company_size: str | None = Field(
        default=None,
        description="startup | smb | enterprise | unknown",
    )
    industry: str | None = Field(
        default=None,
        description="Industry vertical (SaaS, Fintech, HealthTech, etc.)",
    )
    contact_name: str | None = Field(
        default=None,
        description="Contact person name",
    )
    contact_title: str | None = Field(
        default=None,
        description="Job title",
    )
    icp_fit_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="ICP match score 0-100",
    )
    outreach_draft: str | None = Field(
        default=None,
        description="Personalized outreach message",
    )

    # ── Metadata fields (audit trail) ───────────────────────────────────────────
    source: str = Field(
        default="",
        description="Data source identifier (tracxn, hacker_news, etc.)",
    )
    source_url: str = Field(
        default="",
        description="Original URL of the signal",
    )
    model_used: str = Field(
        default="",
        description="Gemini model version used",
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="Total tokens consumed by Gemini API",
    )
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of analysis",
    )

    # ── Pydantic Configuration ───────────────────────────────────────────────────
    model_config = ConfigDict(
        extra="ignore",  # Reject unknown fields (prevent hallucination injection)
        from_attributes=True,  # Allow creation from ORM objects
    )

    # ── Colvin Validator Logic (3 rules) ───────────────────────────────────────

    @model_validator(mode="after")
    def validate_confidence_evidence(self) -> AnalyzedLead:
        """
        Rule 1: High confidence (>0.7) requires evidence in enrichment fields.
        High confidence without supporting data is suspicious - downgrade.
        """
        if self.confidence > 0.7:
            # Check for evidence: company_name or contact_name present
            has_evidence = bool(self.company_name or self.contact_name)
            if not has_evidence:
                # Downgrade confidence - cannot trust high score without evidence
                self.confidence = 0.7
        return self

    @model_validator(mode="after")
    def validate_opportunity_threshold(self) -> AnalyzedLead:
        """
        Rule 2: Opportunity rejected if confidence <0.35.
        Low-confidence opportunities are noise, not signals.
        """
        if self.is_opportunity and self.confidence < 0.35:
            self.is_opportunity = False
            self.reason = f"{self.reason} [AUTO-REJECTED: confidence too low]"
        return self

    @field_validator("intent", mode="before")
    @classmethod
    def validate_intent(cls, v: str) -> str:
        """Ensure intent is from known taxonomy. Returns 'other' if invalid."""
        valid_intents = {
            "buy", "evaluate", "pain", "compare", "other",
            "hiring_urgent", "hiring_planned", "company_growth",
            "open_role", "culture_signal", "compensation_signal",
            "market_gap", "emerging_tech", "hiring",
        }
        if v not in valid_intents:
            return "other"
        return v

    @field_validator("urgency", mode="before")
    @classmethod
    def validate_urgency(cls, v: str) -> str:
        """Ensure urgency is high/medium/low. Returns 'low' if invalid."""
        valid_urgency = {"high", "medium", "low"}
        if v not in valid_urgency:
            return "low"
        return v

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dict for persistence in Lead table.
        Matches the existing AnalysisResult.to_dict() format.
        """
        return {
            "is_opportunity": self.is_opportunity,
            "confidence": self.confidence,
            "intent": self.intent,
            "urgency": self.urgency,
            "reason": self.reason,
            "company_name": self.company_name,
            "company_size": self.company_size,
            "industry": self.industry,
            "contact_name": self.contact_name,
            "contact_title": self.contact_title,
            "icp_fit_score": self.icp_fit_score,
            "outreach_draft": self.outreach_draft,
            "source": self.source,
            "source_url": self.source_url,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "analyzed_at": self.analyzed_at.isoformat(),
        }
