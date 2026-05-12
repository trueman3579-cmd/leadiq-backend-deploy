"""
api/schemas.py — Pydantic request/response models for all API routes.
All FastAPI route handlers use these — never raw dicts in route signatures.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: datetime
    version: str = "1.0.0"


# ── Leads ─────────────────────────────────────────────────────────────────────

class LeadOut(BaseModel):
    id: str
    is_opportunity: bool
    confidence: float
    intent: str
    urgency: str
    opportunity_score: float
    icp_fit_score: float
    final_score: float
    priority: str
    score_band: str | None = None
    company_name: str | None
    company_size: str | None
    industry: str | None
    contact_name: str | None
    contact_title: str | None
    stage: str
    notes: str | None
    outreach_draft: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadListResponse(BaseModel):
    leads: list[LeadOut]
    total: int
    page: int = 1
    page_size: int = 50


class LeadUpdateRequest(BaseModel):
    stage: str | None = Field(None, pattern="^(new|contacted|qualified|closed)$")
    priority: str | None = Field(None, pattern="^(high|medium|low)$")
    notes: str | None = None


class LeadUpdateResponse(BaseModel):
    lead: LeadOut


# ── Miner / AI triggers ───────────────────────────────────────────────────────

class TriggerResponse(BaseModel):
    status: str
    message: str
    task_id: str | None = None


# ── Stats ─────────────────────────────────────────────────────────────────────

class StageCount(BaseModel):
    stage: str
    count: int
    avg_score: float


class PipelineStatsResponse(BaseModel):
    total_leads: int
    hot_leads: int
    warm_leads: int
    avg_final_score: float
    by_stage: list[StageCount]
    collected_today: int
    analyzed_today: int
    stream_lengths: dict[str, int]


# ── Admin ─────────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    lead_id: str
    rating: int = Field(..., ge=1, le=5)
    label: str | None = Field(None, pattern="^(good|bad|duplicate)$")
    reviewer: str | None = None


class FeedbackResponse(BaseModel):
    id: int
    lead_id: str
    rating: int
    label: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── User Profile ──────────────────────────────────────────────────────────────

class UserProfileRequest(BaseModel):
    """Create or update the singleton user profile."""
    mode: str = Field(
        "b2b_sales",
        pattern="^(b2b_sales|hiring|job_search|opportunity)$",
        description="Operational mode — drives query generation and scoring.",
    )
    product_description: str | None = Field(
        None, description="What you sell or who you are."
    )
    target_customer: str | None = Field(
        None, description="Your ideal customer persona."
    )
    target_industries: list[str] = Field(
        default_factory=list,
        description="Industry verticals to prioritise [saas, fintech, …].",
    )
    target_company_sizes: list[str] = Field(
        default_factory=list,
        description="Company sizes to target [startup, smb, enterprise].",
    )
    include_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords that boost lead scores.",
    )
    exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords that block leads from surfacing.",
    )
    hiring_roles: list[str] = Field(
        default_factory=list,
        description="Roles to target (hiring mode).",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Your skills / target tech stack (job_search mode).",
    )
    min_salary: int = Field(0, ge=0, description="Minimum salary filter (job_search).")
    remote_only: bool = Field(False, description="Only remote positions (job_search).")


class UserProfileResponse(BaseModel):
    id: int
    mode: str
    product_description: str | None
    target_customer: str | None
    target_industries: list[str]
    target_company_sizes: list[str]
    include_keywords: list[str]
    exclude_keywords: list[str]
    hiring_roles: list[str]
    skills: list[str]
    min_salary: int
    remote_only: bool
    feedback_adjustments: dict[str, Any]
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Personalised Lead ─────────────────────────────────────────────────────────

class PersonalizedLeadOut(LeadOut):
    """LeadOut extended with live personalization breakdown."""
    personalized_score: float = Field(0.0, description="Profile-adjusted ranking score 0–100.")
    temporal_decay:     float = Field(1.0, description="Freshness weight (1.0 = brand new).")
    profile_fit:        float = Field(1.0, description="Profile-fit multiplier (>1 = strong match).")
    keyword_bonus:      float = Field(0.0, description="Points added from include_keywords matches.")
    feedback_bonus:     float = Field(0.0, description="Points from learned feedback history.")
    velocity_bonus:     float = Field(0.0, description="Points from cross-platform signal velocity.")


# ── Dead Letter Queue (DLQ) ────────────────────────────────────────────────────

class LeadDLQRead(BaseModel):
    """Schema for LeadDLQ response data."""
    id: str
    original_lead_id: str | None
    original_lead_data: dict[str, Any]
    failure_type: str
    error_message: str | None
    retry_count: int
    max_retries: int
    stage: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    lead_id: str | None
    source_url: str | None


class DLQStats(BaseModel):
    """Schema for DLQ statistics."""
    total: int
    by_stage: dict[str, int]
    by_task: dict[str, int]
    failed_permanent: int
    oldest_failure: datetime | None


class DLQDashboardResponse(BaseModel):
    """Schema for full DLQ dashboard response."""
    stats: DLQStats
    recent_failures: list[LeadDLQRead]


class DLQRetryRequest(BaseModel):
    """Request for retrying a DLQ record."""
    pass  # No input needed - just DLQ ID in path


class DLQRetryResponse(BaseModel):
    """Response for DLQ retry action."""
    status: str
    dlq_id: str
    task_name: str
    next_retry_at: datetime


class DLQResolveResponse(BaseModel):
    """Response for DLQ resolve action."""
    status: str
    dlq_id: str


class DLQDeleteResponse(BaseModel):
    """Response for DLQ delete action."""
    status: str
    dlq_id: str


class DLQStatsResponse(BaseModel):
    """Response for DLQ stats endpoint."""
    stats: DLQStats
