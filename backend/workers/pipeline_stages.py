"""
backend/workers/pipeline_stages.py — Pipeline Stage Workers.

Celery tasks for each stage of the pipeline:
  1. process_collected_lead  — Process newly collected lead from stream
  2. enrich_lead             — Run enrichment waterfall (Hunter.io -> Clearbit -> Gemini)
  3. score_lead              — Run composite scoring
  4. rank_lead               — Classify into band and route
  5. handle_routing          — Execute routing rules based on band

These tasks are designed to be chained or called individually from stream consumers.
They reuse existing services from backend/services/ and backend/services/pipeline_orchestrator.py.
"""
from __future__ import annotations

import asyncio
import structlog
import uuid
from datetime import datetime, UTC
from typing import Any

from backend.shared.config import settings
from backend.shared.stream import redis_stream

logger = structlog.get_logger(__name__)

# ── Async Runner Helper ──────────────────────────────────────────────────────────


def _run_async(coro) -> Any:
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ── Lazy Celery App Import ──────────────────────────────────────────────────────

_celery_app: Any = None


def get_celery_app() -> Any:
    """Get the celery app — imports lazily to avoid circular imports."""
    global _celery_app
    if _celery_app is None:
        from backend.workers.pipeline import celery_app as _ca

        _celery_app = _ca
    return _celery_app


# ── Task Registration ────────────────────────────────────────────────────────────


def register_pipeline_stages(celery_app_instance: Any) -> None:
    """Register all pipeline stage tasks with the given celery_app instance.

    Call this after pipeline.py creates the celery_app to avoid circular imports.
    """
    global _celery_app
    _celery_app = celery_app_instance

    # ── Task 1: Process Collected Lead ───────────────────────────────────────────

    @celery_app_instance.task(
        bind=True,
        name="pipeline_stages.process_collected_lead",
        max_retries=3,
        default_retry_delay=30,
        soft_time_limit=120,
        time_limit=150,
        acks_late=True,
    )
    def process_collected_lead_task(
        self,
        lead_id: str,
        source: str,
    ) -> dict[str, Any]:
        """Process a newly collected lead.

        Steps:
            1. Deduplicate the lead (content hash + vector similarity)
            2. If unique, persist to database
            3. Emit to enrichment stream

        Args:
            lead_id: UUID of the lead
            source: Source identifier (naukri, dpiit, github, etc.)

        Returns:
            Dict with processing status
        """
        async def _run() -> dict[str, Any]:
            from backend.services.deduplication import DeduplicationService
            from backend.shared.db import get_db_session
            from backend.shared.repository import LeadRepo

            dedup_service = DeduplicationService()

            async with get_db_session() as session:
                repo = LeadRepo(session)
                lead = await repo.get(lead_id)

                if not lead:
                    logger.warning(
                        "process_collected_lead_not_found",
                        lead_id=lead_id,
                        source=source,
                    )
                    return {"status": "not_found", "lead_id": lead_id}

                # Convert to dict for dedup check
                lead_dict = {
                    "company_name": lead.company_name,
                    "industry": lead.industry,
                    "email": getattr(lead, "email", None),
                    "linkedin_url": getattr(lead, "linkedin_url", None),
                    "company_domain": getattr(lead, "company_domain", None),
                    "embedding": getattr(lead, "embedding", None),
                }

                # Check for duplicates
                dup_check = await dedup_service.check_duplicate(lead_dict, session)

                if dup_check["is_duplicate"]:
                    logger.info(
                        "process_collected_lead_duplicate",
                        lead_id=lead_id,
                        match_type=dup_check["match_type"],
                        existing_id=dup_check["existing_lead_id"],
                    )
                    return {
                        "status": "duplicate",
                        "lead_id": lead_id,
                        "match_type": dup_check["match_type"],
                        "existing_lead_id": dup_check["existing_lead_id"],
                    }

                # Update lead stage to indicate processing
                await repo.update_fields(lead_id, {
                    "stage": "processing",
                    "updated_at": datetime.now(UTC),
                })

                # Emit to enrichment stream
                from backend.events.emitter import emit

                await emit("lead_enriched", {
                    "id": lead_id,
                    "source": source,
                    "stage": "processing",
                })

                logger.info(
                    "process_collected_lead_complete",
                    lead_id=lead_id,
                    source=source,
                )

                return {
                    "status": "accepted",
                    "lead_id": lead_id,
                    "source": source,
                }

        try:
            return _run_async(_run())
        except Exception as exc:
            logger.error(
                "process_collected_lead_failed",
                lead_id=lead_id,
                source=source,
                error=str(exc),
            )
            raise self.retry(exc=exc) from exc

    # ── Task 2: Enrich Lead ──────────────────────────────────────────────────────

    @celery_app_instance.task(
        bind=True,
        name="pipeline_stages.enrich_lead",
        max_retries=3,
        default_retry_delay=30,
        soft_time_limit=60,
        time_limit=90,
        acks_late=True,
    )
    def enrich_lead_task(
        self,
        lead_id: str,
    ) -> dict[str, Any]:
        """Run the enrichment waterfall for a lead.

        Uses PipelineOrchestrator.run_enrichment() which calls:
            1. Hunter.io email extraction
            2. Clearbit company enrichment
            3. Gemini fallback for missing fields

        Args:
            lead_id: UUID of the lead to enrich

        Returns:
            Dict with enrichment results
        """
        async def _run() -> dict[str, Any]:
            from backend.services.pipeline_orchestrator import PipelineOrchestrator

            orchestrator = PipelineOrchestrator()
            result = await orchestrator.run_enrichment(lead_id)

            if result.get("status") == "failed":
                logger.error("enrich_lead_failed", lead_id=lead_id, error=result.get("error"))
                raise RuntimeError(result.get("error", "Enrichment failed"))

            logger.info(
                "enrich_lead_complete",
                lead_id=lead_id,
                methods=result.get("enrichment_methods", []),
            )
            return result

        try:
            return _run_async(_run())
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("enrich_lead_task_failed", lead_id=lead_id, error=str(exc))
            raise self.retry(exc=exc) from exc

    # ── Task 3: Score Lead ───────────────────────────────────────────────────────

    @celery_app_instance.task(
        bind=True,
        name="pipeline_stages.score_lead",
        max_retries=2,
        default_retry_delay=15,
        soft_time_limit=30,
        time_limit=45,
        acks_late=True,
    )
    def score_lead_task(
        self,
        lead_id: str,
    ) -> dict[str, Any]:
        """Run composite scoring on a lead.

        Uses PipelineOrchestrator.run_scoring() which computes:
            - Opportunity score (40%)
            - ICP fit score (30%)
            - Confidence (20%)
            - Intent signals (10%)

        Args:
            lead_id: UUID of the lead to score

        Returns:
            Dict with score, band, and component breakdown
        """
        async def _run() -> dict[str, Any]:
            from backend.services.pipeline_orchestrator import PipelineOrchestrator

            orchestrator = PipelineOrchestrator()
            result = await orchestrator.run_scoring(lead_id)

            if result.get("status") == "failed":
                logger.error("score_lead_failed", lead_id=lead_id, error=result.get("error"))
                raise RuntimeError(result.get("error", "Scoring failed"))

            logger.info(
                "score_lead_complete",
                lead_id=lead_id,
                score=result.get("final_score"),
                band=result.get("score_band"),
            )
            return result

        try:
            return _run_async(_run())
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("score_lead_task_failed", lead_id=lead_id, error=str(exc))
            raise self.retry(exc=exc) from exc

    # ── Task 4: Rank Lead ────────────────────────────────────────────────────────

    @celery_app_instance.task(
        bind=True,
        name="pipeline_stages.rank_lead",
        max_retries=2,
        default_retry_delay=15,
        soft_time_limit=30,
        time_limit=45,
        acks_late=True,
    )
    def rank_lead_task(
        self,
        lead_id: str,
    ) -> dict[str, Any]:
        """Classify a scored lead into a band (hot/warm/cool/cold) and route.

        Args:
            lead_id: UUID of the scored lead

        Returns:
            Dict with band classification and routing info
        """
        async def _run() -> dict[str, Any]:
            from backend.shared.db import get_db_session
            from backend.shared.repository import LeadRepo

            async with get_db_session() as session:
                repo = LeadRepo(session)
                lead = await repo.get(lead_id)

                if not lead:
                    return {"status": "not_found", "lead_id": lead_id}

                final_score = float(lead.final_score or 0.0)

                # Determine band
                if final_score >= 80:
                    band = "hot"
                elif final_score >= 60:
                    band = "warm"
                elif final_score >= 40:
                    band = "cool"
                else:
                    band = "cold"

                # Persist band
                await repo.update_fields(lead_id, {
                    "score_band": band,
                })

                # Publish to ranked stream
                from backend.events.emitter import emit

                await emit("lead_ranked", {
                    "id": lead_id,
                    "final_score": final_score,
                    "score_band": band,
                })

                logger.info(
                    "rank_lead_complete",
                    lead_id=lead_id,
                    score=final_score,
                    band=band,
                )

                return {
                    "status": "ranked",
                    "lead_id": lead_id,
                    "final_score": final_score,
                    "score_band": band,
                }

        try:
            return _run_async(_run())
        except Exception as exc:
            logger.error("rank_lead_task_failed", lead_id=lead_id, error=str(exc))
            raise self.retry(exc=exc) from exc

    # ── Task 5: Handle Routing ───────────────────────────────────────────────────

    @celery_app_instance.task(
        bind=True,
        name="pipeline_stages.handle_routing",
        max_retries=2,
        default_retry_delay=30,
        soft_time_limit=60,
        time_limit=90,
        acks_late=True,
    )
    def handle_routing_task(
        self,
        lead_id: str,
        band: str,
    ) -> dict[str, Any]:
        """Execute routing rules based on lead band classification.

        Routing rules:
            - hot:    Immediate outreach — trigger email + LinkedIn sequence
            - warm:   Nurture sequence — add to automated email drip
            - cool:   Long-term nurture — schedule monthly check-in
            - cold:   Drip campaign — add to quarterly newsletter list

        Args:
            lead_id: UUID of the lead
            band: Score band (hot/warm/cool/cold)

        Returns:
            Dict with routing action and status
        """
        async def _run() -> dict[str, Any]:
            from backend.shared.db import get_db_session
            from backend.shared.repository import LeadRepo
            from backend.events.emitter import emit

            routing_actions: dict[str, str] = {
                "hot": "immediate_outreach",
                "warm": "nurture_sequence",
                "cool": "long_term_nurture",
                "cold": "drip_campaign",
            }

            action = routing_actions.get(band, "drip_campaign")
            priority = "high" if band in ("hot", "warm") else "low"

            async with get_db_session() as session:
                repo = LeadRepo(session)
                lead = await repo.get(lead_id)

                if not lead:
                    return {"status": "not_found", "lead_id": lead_id}

                # Update lead stage based on routing
                stage_map: dict[str, str] = {
                    "immediate_outreach": "contacted",
                    "nurture_sequence": "nurturing",
                    "long_term_nurture": "nurturing",
                    "drip_campaign": "new",
                }
                new_stage = stage_map.get(action, "new")

                await repo.update_fields(lead_id, {
                    "stage": new_stage,
                    "priority": priority,
                })

                # Emit routing event
                await emit("lead_ranked", {
                    "id": lead_id,
                    "action": action,
                    "band": band,
                    "priority": priority,
                })

                # Publish to the outreach stream for immediate actions
                if action == "immediate_outreach":
                    from backend.shared.stream import redis_stream

                    try:
                        await redis_stream.publish(
                            settings.STREAM_OUTREACH,
                            {
                                "lead_id": lead_id,
                                "action": action,
                                "priority": priority,
                                "routed_at": datetime.now(UTC).isoformat(),
                            },
                        )
                    except Exception as pub_exc:
                        logger.warning(
                            "routing_outreach_publish_failed",
                            lead_id=lead_id,
                            error=str(pub_exc),
                        )

                logger.info(
                    "handle_routing_complete",
                    lead_id=lead_id,
                    band=band,
                    action=action,
                    priority=priority,
                )

                return {
                    "status": "routed",
                    "lead_id": lead_id,
                    "band": band,
                    "action": action,
                    "priority": priority,
                    "stage": new_stage,
                }

        try:
            return _run_async(_run())
        except Exception as exc:
            logger.error("handle_routing_task_failed", lead_id=lead_id, band=band, error=str(exc))
            raise self.retry(exc=exc) from exc

    # ── Task Router Registration ─────────────────────────────────────────────────

    try:
        from backend.workers.dlq import TASK_ROUTER

        TASK_ROUTER["pipeline_stages.process_collected_lead"] = (
            lambda a, k: process_collected_lead_task.apply_async(args=a, kwargs=k)
        )
        TASK_ROUTER["pipeline_stages.enrich_lead"] = (
            lambda a, k: enrich_lead_task.apply_async(args=a, kwargs=k)
        )
        TASK_ROUTER["pipeline_stages.score_lead"] = (
            lambda a, k: score_lead_task.apply_async(args=a, kwargs=k)
        )
        TASK_ROUTER["pipeline_stages.rank_lead"] = (
            lambda a, k: rank_lead_task.apply_async(args=a, kwargs=k)
        )
        TASK_ROUTER["pipeline_stages.handle_routing"] = (
            lambda a, k: handle_routing_task.apply_async(args=a, kwargs=k)
        )
        logger.info("pipeline_stages_tasks_registered_in_router")
    except Exception:
        logger.warning("TASK_ROUTER not available — skipping registration")

    # Return references so the caller can store them at module level
    return (
        process_collected_lead_task,
        enrich_lead_task,
        score_lead_task,
        rank_lead_task,
        handle_routing_task,
    )


# ── Module-level task references (populated by setup_pipeline_stages) ────────────

process_collected_lead_task: Any = None
enrich_lead_task: Any = None
score_lead_task: Any = None
rank_lead_task: Any = None
handle_routing_task: Any = None


def setup_pipeline_stages(celery_app_instance: Any) -> None:
    """Setup pipeline stage tasks with the celery app.

    Call this after pipeline.py creates the app and after actors are set up.
    """
    global process_collected_lead_task, enrich_lead_task
    global score_lead_task, rank_lead_task, handle_routing_task

    (
        process_collected_lead_task,
        enrich_lead_task,
        score_lead_task,
        rank_lead_task,
        handle_routing_task,
    ) = register_pipeline_stages(celery_app_instance)

    logger.info("pipeline_stages_setup_complete")
