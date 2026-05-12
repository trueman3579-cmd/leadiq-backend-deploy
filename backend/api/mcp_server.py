"""
api/mcp_server.py — Remote MCP Server (Streamable HTTP transport).

Exposes LeadIQ tools via the Model Context Protocol so that AI agents
(Copilot, Claude, etc.) can query leads, trigger collection, and manage
the pipeline from any MCP client.

Mount in main.py:  app.mount("/mcp", mcp_app)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── MCP instance ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    "LeadIQ",
    instructions=(
        "LeadIQ is an AI-powered B2B lead intelligence platform. "
        "Use these tools to search leads, view pipeline stats, trigger "
        "collection runs, and manage the sales pipeline."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _lead_to_dict(lead) -> dict[str, Any]:
    """Convert a SQLAlchemy Lead row into a plain dict for MCP responses."""
    return {
        "id": str(lead.id),
        "is_opportunity": lead.is_opportunity,
        "confidence": lead.confidence,
        "intent": lead.intent,
        "urgency": lead.urgency,
        "opportunity_score": lead.opportunity_score,
        "icp_fit_score": lead.icp_fit_score,
        "final_score": lead.final_score,
        "score_band": lead.score_band,
        "priority": lead.priority,
        "company_name": lead.company_name,
        "company_size": lead.company_size,
        "industry": lead.industry,
        "contact_name": lead.contact_name,
        "contact_title": lead.contact_title,
        "stage": lead.stage,
        "notes": lead.notes,
        "outreach_draft": lead.outreach_draft,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _verify_mcp_api_key(api_key: str | None) -> bool:
    """Check the MCP_API_KEY env var. Empty key is rejected."""
    expected = os.getenv("MCP_API_KEY", "")
    if not expected:
        return False  # No key configured → reject all requests
    return api_key == expected


# ── Resources ────────────────────────────────────────────────────────────────

@mcp.resource("leadiq://status")
async def get_status() -> str:
    """Current system status and configuration summary."""
    from backend.shared.config import settings
    return (
        f"LeadIQ v2.0.0\n"
        f"Mode: {settings.GEMINI_MODEL}\n"
        f"DB: {'configured' if settings.DATABASE_URL else 'not configured'}\n"
        f"Redis: {'configured' if settings.REDIS_URL else 'not configured'}\n"
        f"Collectors: Reddit, HN, Twitter, RSS, GitHub, ProductHunt, StackOverflow\n"
        f"Timestamp: {datetime.now(UTC).isoformat()}"
    )


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_leads(
    stage: str | None = None,
    min_score: float = 0.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    List leads from the database with optional filtering.

    Args:
        stage: Filter by pipeline stage (new, contacted, qualified, closed)
        min_score: Minimum final_score threshold (0-100)
        limit: Max results to return (1-200)
    """
    from backend.shared.db import get_db_session
    from backend.shared.repository import LeadRepo

    async with get_db_session() as session:
        repo = LeadRepo(session)
        leads = await repo.list_all(
            stage=stage,
            min_score=min_score,
            limit=min(limit, 200),
        )
        return [_lead_to_dict(lead) for lead in leads]


@mcp.tool()
async def get_lead(lead_id: str) -> dict[str, Any]:
    """
    Get a single lead by its UUID.

    Args:
        lead_id: The UUID of the lead to retrieve
    """
    from backend.shared.db import get_db_session
    from backend.shared.repository import LeadRepo

    async with get_db_session() as session:
        repo = LeadRepo(session)
        lead = await repo.get(lead_id)
        if not lead:
            return {"error": f"Lead {lead_id} not found"}
        return _lead_to_dict(lead)


@mcp.tool()
async def get_hot_leads(limit: int = 10) -> list[dict[str, Any]]:
    """
    Get the highest-scoring leads (score >= 80, aka 'hot' band).

    Args:
        limit: Max results to return
    """
    from backend.shared.db import get_db_session
    from backend.shared.repository import LeadRepo

    async with get_db_session() as session:
        repo = LeadRepo(session)
        leads = await repo.list_all(min_score=80.0, limit=min(limit, 100))
        return [_lead_to_dict(lead) for lead in leads]


@mcp.tool()
async def search_leads(
    query: str,
    min_score: float = 0.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Search leads by company name, industry, intent, or notes.

    Args:
        query: Search text to match against company_name, industry, intent, notes
        min_score: Minimum score filter
        limit: Max results
    """
    from sqlalchemy import or_, select
    from backend.shared.db import get_db_session
    from backend.shared.models import Lead

    q = query.lower()
    async with get_db_session() as session:
        stmt = (
            select(Lead)
            .where(
                Lead.final_score >= min_score,
                or_(
                    Lead.company_name.ilike(f"%{q}%"),
                    Lead.industry.ilike(f"%{q}%"),
                    Lead.intent.ilike(f"%{q}%"),
                    Lead.notes.ilike(f"%{q}%"),
                    Lead.contact_name.ilike(f"%{q}%"),
                ),
            )
            .order_by(Lead.final_score.desc())
            .limit(min(limit, 200))
        )
        result = await session.execute(stmt)
        leads = list(result.scalars().all())
        return [_lead_to_dict(lead) for lead in leads]


@mcp.tool()
async def get_pipeline_stats() -> dict[str, Any]:
    """Get pipeline statistics: total leads, hot/warm counts, avg scores, stage breakdown."""
    from sqlalchemy import func, select
    from backend.shared.db import get_db_session
    from backend.shared.models import Lead

    async with get_db_session() as session:
        total = (await session.execute(select(func.count(Lead.id)))).scalar() or 0
        hot = (await session.execute(
            select(func.count(Lead.id)).where(Lead.final_score >= 80)
        )).scalar() or 0
        warm = (await session.execute(
            select(func.count(Lead.id)).where(Lead.final_score >= 60, Lead.final_score < 80)
        )).scalar() or 0
        avg_score = round(float(
            (await session.execute(select(func.avg(Lead.final_score)))).scalar() or 0.0
        ), 1)

        stage_result = await session.execute(
            select(Lead.stage, func.count(Lead.id), func.avg(Lead.final_score))
            .group_by(Lead.stage)
        )
        by_stage = {
            row[0]: {"count": row[1], "avg_score": round(row[2] or 0.0, 1)}
            for row in stage_result.all()
        }

        return {
            "total_leads": total,
            "hot_leads": hot,
            "warm_leads": warm,
            "avg_final_score": avg_score,
            "by_stage": by_stage,
        }


@mcp.tool()
async def update_lead_stage(
    lead_id: str,
    stage: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Move a lead to a new pipeline stage.

    Args:
        lead_id: UUID of the lead
        stage: New stage (new, contacted, qualified, closed)
        notes: Optional notes to attach
    """
    valid_stages = {"new", "contacted", "qualified", "closed"}
    if stage not in valid_stages:
        return {"error": f"Invalid stage. Must be one of: {valid_stages}"}

    from backend.shared.db import get_db_session
    from backend.shared.repository import LeadRepo

    updates: dict[str, Any] = {"stage": stage}
    if notes is not None:
        updates["notes"] = notes

    async with get_db_session() as session:
        repo = LeadRepo(session)
        lead = await repo.update_fields(lead_id, updates)
        if not lead:
            return {"error": f"Lead {lead_id} not found"}
        return _lead_to_dict(lead)


@mcp.tool()
async def trigger_collection() -> dict[str, str]:
    """
    Trigger a new lead collection run across all configured sources
    (Reddit, HN, Twitter, RSS, GitHub, ProductHunt, StackOverflow).
    """
    try:
        from backend.workers.pipeline import collect_and_publish
        task = collect_and_publish.delay()
        return {"status": "queued", "task_id": task.id, "message": "Collection pipeline started via Celery"}
    except Exception:
        return {"status": "error", "message": "Celery not available. Start the collection worker first."}


@mcp.tool()
async def trigger_analysis() -> dict[str, str]:
    """Trigger AI analysis on collected but unanalyzed leads using Gemini."""
    try:
        from backend.workers.pipeline import run_analysis_consumer
        task = run_analysis_consumer.delay()
        return {"status": "queued", "task_id": task.id, "message": "AI analysis pipeline started"}
    except Exception:
        return {"status": "error", "message": "Celery not available. Start the analysis worker first."}


@mcp.tool()
async def get_user_profile() -> dict[str, Any]:
    """Get the current user profile including operation mode, target industries, and keywords."""
    from backend.shared.db import get_db_session
    from backend.shared.repository import ProfileRepo

    async with get_db_session() as session:
        repo = ProfileRepo(session)
        profile = await repo.get_active()
        if not profile:
            return {
                "mode": "b2b_sales",
                "message": "No profile configured yet. Using defaults.",
            }
        return {
            "id": profile.id,
            "mode": profile.mode,
            "product_description": profile.product_description,
            "target_customer": profile.target_customer,
            "target_industries": profile.target_industries,
            "target_company_sizes": profile.target_company_sizes,
            "include_keywords": profile.include_keywords,
            "exclude_keywords": profile.exclude_keywords,
            "hiring_roles": profile.hiring_roles,
            "skills": profile.skills,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }


@mcp.tool()
async def get_velocity_signals(limit: int = 10) -> list[dict[str, Any]]:
    """
    Get cross-source velocity signals — companies appearing on multiple platforms.

    Args:
        limit: Number of top companies to return
    """
    from backend.services.velocity import velocity_tracker

    try:
        top = await velocity_tracker.get_top_companies(limit=limit)
        return [
            {"company": name, "signal_count": count}
            for name, count in top
        ]
    except Exception:
        return [{"error": "Velocity tracker not connected. Ensure Redis is running."}]


@mcp.tool()
async def submit_feedback(
    lead_id: str,
    rating: int,
    label: str | None = None,
) -> dict[str, Any]:
    """
    Submit human feedback on a lead (used for scoring calibration).

    Args:
        lead_id: UUID of the lead
        rating: Quality rating from 1 (bad) to 5 (excellent)
        label: Optional label: good, bad, or duplicate
    """
    if rating < 1 or rating > 5:
        return {"error": "Rating must be between 1 and 5"}
    if label and label not in {"good", "bad", "duplicate"}:
        return {"error": "Label must be one of: good, bad, duplicate"}

    from backend.shared.db import get_db_session
    from backend.shared.repository import FeedbackRepo

    async with get_db_session() as session:
        repo = FeedbackRepo(session)
        fb = await repo.create(lead_id=lead_id, rating=rating, label=label, reviewer="mcp-agent")
        return {
            "id": fb.id,
            "lead_id": str(fb.lead_id),
            "rating": fb.rating,
            "label": fb.label,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        }


# ── Prompts ──────────────────────────────────────────────────────────────────

@mcp.prompt()
def lead_analysis_prompt(lead_id: str) -> str:
    """Generate a prompt for analyzing a specific lead in detail."""
    return (
        f"Analyze lead {lead_id} from the LeadIQ pipeline. "
        f"First use get_lead to fetch the lead details. Then:\n"
        f"1. Assess the opportunity quality based on score, intent, and urgency\n"
        f"2. Evaluate company fit (size, industry)\n"
        f"3. Suggest next steps for outreach\n"
        f"4. Rate the lead's priority and recommend a pipeline action"
    )


@mcp.prompt()
def pipeline_review_prompt() -> str:
    """Generate a prompt for reviewing the entire pipeline health."""
    return (
        "Review the LeadIQ pipeline health by:\n"
        "1. Use get_pipeline_stats to get overall numbers\n"
        "2. Use get_hot_leads to see the best current opportunities\n"
        "3. Use get_velocity_signals to find trending companies\n"
        "4. Summarize: total volume, conversion rates by stage, top 3 actionable leads\n"
        "5. Recommend: which leads to contact first and why"
    )


# ── ASGI app for mounting ────────────────────────────────────────────────────

mcp_app = mcp.streamable_http_app()
