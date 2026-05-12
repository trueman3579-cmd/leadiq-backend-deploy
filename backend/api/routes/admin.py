"""
api/routes/admin.py — Admin endpoints: feedback, lead deletion, quota stats, DLQ CRUD.

POST  /api/admin/feedback        → submit lead quality feedback  [auth required]
GET   /api/admin/feedback/{id}   → list feedback for a lead      [auth required]
DELETE /api/admin/lead/{id}      → soft-delete a lead            [auth required]
GET   /api/admin/quota           → Gemini API quota usage today  [auth required]
GET   /api/admin/deploy-check    → verify deployment readiness   [auth required]
GET   /api/admin/dlq             → full DLQ dashboard            [auth required]
POST  /api/admin/dlq/{id}/retry  → retry a failed task          [auth required]
POST  /api/admin/dlq/{id}/resolve→ mark as resolved             [auth required]
DELETE /api/admin/dlq/{id}       → hard delete DLQ record       [auth required]
GET   /api/admin/dlq/stats       → DLQ statistics only          [auth required]
"""
from __future__ import annotations

import structlog
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.api.deps import DbSession, CurrentUser
from backend.api.schemas import (
    DLQDashboardResponse,
    DLQDeleteResponse,
    DLQRetryRequest,
    DLQRetryResponse,
    DLQResolveResponse,
    DLQStats,
    DLQStatsResponse,
    FeedbackRequest,
    FeedbackResponse,
    LeadDLQRead,
)
from backend.models.lead_dlq import LeadDLQ, LeadDLQStage
from backend.shared.repository import FeedbackRepo, LeadRepo, QuotaRepo, ProfileRepo
from backend.shared.config import settings
from backend.shared.stream import redis_stream


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    body: FeedbackRequest,
    session: DbSession,
    _user: CurrentUser,                          # ← requires valid JWT
) -> FeedbackResponse:
    lead_repo = LeadRepo(session)
    lead = await lead_repo.get(body.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    fb_repo = FeedbackRepo(session)
    fb = await fb_repo.create(
        lead_id=body.lead_id,
        rating=body.rating,
        label=body.label,
        reviewer=body.reviewer,
    )

    # ── Feedback learning: update profile scoring weights ────────────────────
    try:
        from backend.services.personalization import record_feedback
        profile_repo = ProfileRepo(session)
        profile = await profile_repo.get_active()
        if profile:
            new_adj = record_feedback(
                dict(profile.feedback_adjustments or {}),
                industry=lead.industry,
                intent=lead.intent or "other",
                rating=body.rating,
            )
            await profile_repo.update_feedback_adjustments(new_adj)
    except Exception:
        pass  # learning is best-effort; never fail the feedback write

    return FeedbackResponse.model_validate(fb)


@router.get("/feedback/{lead_id}", response_model=list[FeedbackResponse])
async def list_feedback(
    lead_id: str,
    session: DbSession,
    _user: CurrentUser,
) -> list[FeedbackResponse]:
    fb_repo = FeedbackRepo(session)
    feedbacks = await fb_repo.list_by_lead(lead_id)
    return [FeedbackResponse.model_validate(fb) for fb in feedbacks]


@router.delete("/lead/{lead_id}", status_code=204, response_class=Response)
async def delete_lead(
    lead_id: str,
    session: DbSession,
    _user: CurrentUser,
) -> Response:
    repo = LeadRepo(session)
    lead = await repo.update_fields(lead_id, {"stage": "closed"})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return Response(status_code=204)


@router.get("/quota")
async def get_quota(
    session: DbSession,
    _user: CurrentUser,
) -> dict:
    repo = QuotaRepo(session)
    today = date.today().isoformat()
    usage = await repo.get_daily_total(model=settings.GEMINI_MODEL, day=today)
    return {
        "date": today,
        "model": settings.GEMINI_MODEL,
        "tokens_used": usage.tokens_used if usage else 0,
        "requests_count": usage.requests_count if usage else 0,
    }


@router.get("/deploy-check")
async def deploy_check(
    session: DbSession,
    _user: CurrentUser,
) -> dict[str, Any]:
    """
    Deployment readiness check.

    Verifies:
        - Database connection
        - Redis connectivity
        - Gemini API key configured
        - Required models exist
    """
    result: dict[str, Any] = {
        "status": "healthy",
        "checks": {},
        "errors": [],
    }

    # Check database
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
        result["checks"]["database"] = "ok"
    except Exception as e:
        result["checks"]["database"] = "error"
        result["errors"].append(f"Database: {str(e)}")
        result["status"] = "unhealthy"

    # Check Redis
    try:
        r = redis_stream._r if redis_stream._r else None
        if r:
            await r.ping()
            result["checks"]["redis"] = "ok"
        else:
            result["checks"]["redis"] = "not_connected"
    except Exception as e:
        result["checks"]["redis"] = "error"
        result["errors"].append(f"Redis: {str(e)}")
        result["status"] = "unhealthy"

    # Check Gemini API key
    if settings.GEMINI_API_KEY:
        result["checks"]["gemini_api"] = "configured"
    else:
        result["checks"]["gemini_api"] = "missing"
        result["errors"].append("GEMINI_API_KEY not set")
        result["status"] = "unhealthy"

    # Check database tables exist
    try:
        from sqlalchemy import text
        tables = ["leads", "icps", "lead_events", "profiles"]
        for table in tables:
            table_result = await session.execute(
                text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)").params(t=table)
            )
            exists = table_result.scalar()
            result["checks"][f"table_{table}"] = "ok" if exists else "missing"
    except Exception as e:
        result["checks"]["table_check"] = "error"
        result["errors"].append(f"Table check: {str(e)}")

    # Check migration status
    try:
        from sqlalchemy import text
        result = await session.execute(text(
            "SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"
        ))
        row = result.fetchone()
        if row:
            result["checks"]["migration"] = row[0]
        else:
            result["checks"]["migration"] = "no_migrations"
    except Exception as e:
        result["checks"]["migration"] = "error"
        result["errors"].append(f"Migration check: {str(e)}")

    return result


@router.get("/dlq", response_model=DLQDashboardResponse)
async def get_dlq_dashboard(
    session: DbSession,
    _user: CurrentUser,
):
    """Full DLQ dashboard - stats + recent failures."""
    from backend.workers.dlq import DLQWorker
    from backend.shared.stream import redis_stream

    worker = DLQWorker(session, redis_stream._r)
    stats = await worker.get_stats()
    recent = await worker.get_recent(limit=50)

    return DLQDashboardResponse(
        stats=DLQStats(
            total=stats["total"],
            by_stage=stats["by_stage"],
            by_task=stats["by_task"],
            failed_permanent=stats["failed_permanent"],
            oldest_failure=stats["oldest_failure"],
        ),
        recent_failures=[
            LeadDLQRead(
                id=str(r.id),
                original_lead_id=str(r.original_lead_id) if r.original_lead_id else None,
                original_lead_data=r.original_lead_data,
                failure_type=r.failure_type,
                error_message=r.error_message,
                retry_count=r.retry_count,
                max_retries=r.max_retries,
                stage=r.stage,
                created_at=r.created_at,
                updated_at=r.updated_at,
                resolved_at=r.resolved_at,
                resolved_by=r.resolved_by,
                lead_id=str(r.original_lead_id) if r.original_lead_id else None,
                source_url=None,
            )
            for r in recent
        ],
    )


@router.post("/dlq/{dlq_id}/retry", response_model=DLQRetryResponse)
async def retry_dlq_record(
    dlq_id: str,
    body: DLQRetryRequest,
    session: DbSession,
    _user: CurrentUser,
):
    """Manually retry a failed DLQ record."""
    from sqlalchemy import select
    from backend.workers.dlq import TASK_ROUTER
    from backend.workers.pipeline import (
        collect_and_publish,
        run_analysis_consumer,
        run_scoring_consumer,
        persist_scored_leads,
        dedup_lead,
        process_dlq_retries,
    )
    from backend.workers.actors import (
        collect_github,
        search_github_india,
        monitor_telegram,
    )
    import json

    # Wire up task router
    TASK_ROUTER["pipeline.collect_and_publish"] = lambda a, k: collect_and_publish.apply_async(args=a, kwargs=k)
    TASK_ROUTER["pipeline.run_analysis_consumer"] = lambda a, k: run_analysis_consumer.apply_async(args=a, kwargs=k)
    TASK_ROUTER["pipeline.run_scoring_consumer"] = lambda a, k: run_scoring_consumer.apply_async(args=a, kwargs=k)
    TASK_ROUTER["pipeline.persist_scored_leads"] = lambda a, k: persist_scored_leads.apply_async(args=a, kwargs=k)
    TASK_ROUTER["pipeline.dedup_lead"] = lambda a, k: dedup_lead.apply_async(args=a, kwargs=k)
    TASK_ROUTER["pipeline.process_dlq_retries"] = lambda a, k: process_dlq_retries.apply_async(args=a, kwargs=k)
    TASK_ROUTER["actors.collect_github"] = lambda a, k: collect_github.apply_async(args=a, kwargs=k)
    TASK_ROUTER["actors.search_github_india"] = lambda a, k: search_github_india.apply_async(args=a, kwargs=k)
    TASK_ROUTER["actors.monitor_telegram"] = lambda a, k: monitor_telegram.apply_async(args=a, kwargs=k)

    result = await session.execute(select(LeadDLQ).where(LeadDLQ.id == dlq_id))
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="DLQ record not found")

    # Check if can retry
    if not record.can_retry():
        raise HTTPException(status_code=400, detail="Max retries exceeded")

    # Parse original data
    try:
        original_data = json.loads(record.original_lead_data)
        task_name = "pipeline.dedup_lead"  # Default - improve task name extraction
        task_args = original_data.get("args", [])
        task_kwargs = original_data.get("kwargs", {})
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid original data") from exc

    # Get task router entry
    task_func = TASK_ROUTER.get(task_name)
    if task_func is None:
        raise HTTPException(status_code=500, detail=f"No task router for {task_name}")

    try:
        # Re-enqueue task
        task_func(task_args, task_kwargs)

        # Update record
        record.stage = LeadDLQStage.retrying
        record.retry_count += 1
        record.last_retry_at = datetime.utcnow()
        record.next_retry_at = record.calculate_backoff()
        await session.commit()

        return DLQRetryResponse(
            status="requeued",
            dlq_id=dlq_id,
            task_name=task_name,
            next_retry_at=record.next_retry_at,
        )
    except Exception as exc:
        logger = structlog.get_logger()
        logger.error("dlq_retry_failed", dlq_id=dlq_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to requeue: {str(exc)}") from exc


@router.post("/dlq/{dlq_id}/resolve", response_model=DLQResolveResponse)
async def resolve_dlq_record(
    dlq_id: str,
    body: DLQRetryRequest,
    session: DbSession,
    _user: CurrentUser,
):
    """Manually resolve a DLQ record."""
    from sqlalchemy import select
    from backend.workers.dlq import DLQWorker

    result = await session.execute(select(LeadDLQ).where(LeadDLQ.id == dlq_id))
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="DLQ record not found")

    worker = DLQWorker(session, redis_stream._r)
    success = await worker.mark_resolved(dlq_id, _user.username if hasattr(_user, "username") else "admin")

    if not success:
        raise HTTPException(status_code=404, detail="DLQ record not found")

    return DLQResolveResponse(status="resolved", dlq_id=dlq_id)


@router.delete("/dlq/{dlq_id}", response_model=DLQDeleteResponse)
async def delete_dlq_record(
    dlq_id: str,
    session: DbSession,
    _user: CurrentUser,
):
    """Delete a DLQ record (hard delete)."""
    from sqlalchemy import select

    result = await session.execute(select(LeadDLQ).where(LeadDLQ.id == dlq_id))
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="DLQ record not found")

    await session.delete(record)
    await session.commit()

    return DLQDeleteResponse(status="deleted", dlq_id=dlq_id)


@router.get("/dlq/stats", response_model=DLQStatsResponse)
async def get_dlq_stats(
    session: DbSession,
    _user: CurrentUser,
):
    """Get DLQ statistics only (lightweight, for health polling)."""
    from backend.workers.dlq import DLQWorker
    from backend.shared.stream import redis_stream

    worker = DLQWorker(session, redis_stream._r)
    stats = await worker.get_stats()

    return DLQStatsResponse(
        stats=DLQStats(
            total=stats["total"],
            by_stage=stats["by_stage"],
            by_task=stats["by_task"],
            failed_permanent=stats["failed_permanent"],
            oldest_failure=stats["oldest_failure"],
        )
    )


# ── Budget Status (Day 10: Cost Stable) ──────────────────────────────────────


@router.get("/budget-status")
async def budget_status(_user: CurrentUser):
    """Returns current Gemini token budget status (daily + hourly + queue)."""
    from backend.llm.cost_guard import get_budget_status
    return await get_budget_status()


# ── Source Quality Metrics (Day 11: Source Audit) ─────────────────────────────


@router.get("/source-metrics")
async def source_metrics(days: int = 7, _user: CurrentUser = None):
    """Per-source qualification rates over N days."""
    from backend.workers.source_metrics import get_all_source_metrics
    return {"metrics": await get_all_source_metrics(days=days), "window_days": days}


@router.post("/source-audit")
async def trigger_source_audit(days: int = 7, _user: CurrentUser = None):
    """Run full source audit and save to source_audit.json."""
    from backend.workers.source_metrics import run_source_audit
    return await run_source_audit(days=days)


# ── Daily Metrics (Day 13: Celery Beat) ────────────────────────────────────


@router.get("/daily-metrics")
async def get_daily_metrics(days: int = 7, _user: CurrentUser = None):
    """Returns daily metrics for the past N days."""
    import json
    from backend.shared.stream import redis_stream
    from datetime import date, timedelta

    r = redis_stream._r
    if not r:
        return {"error": "Redis not connected"}

    today = date.today()
    metrics_list = []
    for i in range(days):
        day = today - timedelta(days=i)
        key = f"daily_metrics:{day.isoformat()}"
        data = await r.hgetall(key)
        if data:
            parsed = {}
            for k, v in data.items():
                try:
                    parsed[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed[k] = v
            metrics_list.append(parsed)

    return {"metrics": metrics_list, "days": days}


# ── TOS Compliance (Day 12: Legal Clean) ──────────────────────────────────────


@router.get("/compliance")
async def get_compliance(_user: CurrentUser = None):
    """Full compliance posture for all sources."""
    from backend.compliance.tos_registry import get_compliance_summary
    return get_compliance_summary()


@router.get("/compliance/{source}")
async def get_source_compliance(source: str, _user: CurrentUser = None):
    """Compliance posture for a single source."""
    from backend.compliance.tos_registry import check_source_compliance
    result = check_source_compliance(source)
    if result["status"] == "blocked" and result.get("reason"):
        return result
    return result


# ── Prompt Versioning (Day 18) ───────────────────────────────────────────────


@router.get("/prompt-versions")
async def get_prompt_versions(_user: CurrentUser = None):
    """Current prompt versions for all sources."""
    from backend.llm.prompt_versioning import PROMPT_VERSIONS, PROMPT_CHANGELOG
    return {
        "versions": PROMPT_VERSIONS,
        "changelogs": {
            src: log[-5:] for src, log in PROMPT_CHANGELOG.items()
        },
    }


@router.get("/prompt-versions/{source}")
async def get_source_prompt_version(source: str, _user: CurrentUser = None):
    """Prompt version and changelog for a single source."""
    from backend.llm.prompt_versioning import get_prompt_version, get_changelog
    return {
        "source": source,
        "version": get_prompt_version(source),
        "changelog": get_changelog(source),
    }


@router.post("/prompt-versions/{source}/bump")
async def bump_prompt_version(source: str, _user: CurrentUser = None):
    """Bump prompt version for a source (admin only)."""
    from backend.llm.prompt_versioning import bump_prompt_version
    new_ver = bump_prompt_version(source, "Manual bump via admin API")
    return {"source": source, "new_version": new_ver}


@router.post("/ab-experiments")
async def create_ab_experiment(
    name: str = "",
    variants: str = "",
    _user: CurrentUser = None,
):
    """Start an A/B experiment for prompt variants (comma-separated)."""
    from backend.llm.prompt_versioning import start_experiment

    if not name:
        from datetime import datetime
        name = f"experiment_{datetime.now().strftime('%Y%m%d_%H%M')}"

    variant_list = [v.strip() for v in variants.split(",") if v.strip()]
    if len(variant_list) < 2:
        return {"error": "Need at least 2 variants (comma-separated)"}

    return await start_experiment(name, variant_list)


@router.get("/ab-experiments/{experiment_id}")
async def get_ab_experiment(experiment_id: str, _user: CurrentUser = None):
    """Get A/B experiment results."""
    from backend.llm.prompt_versioning import get_ab_results
    return await get_ab_results(experiment_id)


@router.post("/ab-experiments/{experiment_id}/stop")
async def stop_ab_experiment(experiment_id: str, _user: CurrentUser = None):
    """Stop a running A/B experiment."""
    from backend.llm.prompt_versioning import stop_experiment
    return await stop_experiment(experiment_id)

