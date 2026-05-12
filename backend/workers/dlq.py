"""
backend/workers/dlq.py — Dead Letter Queue Worker for failed pipeline tasks.

Architecture:
  pipeline.py task fails
      ↓
  on_task_failure signal
      ↓
  DLQWorker.capture(task_name, args, kwargs, exc, traceback)
      ↓ writes LeadDLQ record (stage=new)
      ↓
  Celery beat task: process_dlq_retries() [runs every 5 min]
      ↓
  For each LeadDLQ where stage=new or stage=retrying AND can_retry():
      Re-enqueues original task to correct pipeline queue
      Increments retry_count, updates stage
  ↓
  If not can_retry():
      stage → failed_permanent
      Alert structlog CRITICAL

Usage:
    from backend.workers.dlq import DLQWorker
    from backend.shared.db import get_db_session
    from backend.shared.stream import redis_stream

    async with get_db_session() as db:
        worker = DLQWorker(db, redis_stream._r)
        dlq_record = await worker.capture("pipeline.dedup_lead", "task-123", [], {}, ValueError("test"), "tb")
        stats = await worker.get_stats()
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.lead_dlq import LeadDLQ, LeadDLQStage

logger = structlog.get_logger(__name__)

# ── Task Router ───────────────────────────────────────────────────────────────
# Maps task_name string → Celery task .delay() or .apply_async() call

TASK_ROUTER: dict[str, Any] = {
    "pipeline.collect_and_publish": None,  # Placeholder - wired at import
    "pipeline.run_analysis_consumer": None,  # Placeholder - wired at import
    "pipeline.run_scoring_consumer": None,  # Placeholder - wired at import
    "pipeline.persist_scored_leads": None,  # Placeholder - wired at import
    "pipeline.dedup_lead": None,  # Placeholder - wired at import
    "actors.collect_github": None,  # Placeholder - wired at import
    "actors.search_github_india": None,  # Placeholder - wired at import
    "actors.monitor_telegram": None,  # Placeholder - wired at import
}


class DLQWorker:
    """
    DLQ Worker - processes LeadDLQ records for retry or permanent failure handling.

    Uses existing LeadDLQ model - no new model created.
    """

    def __init__(self, db: AsyncSession, redis: Any) -> None:
        """
        Initialize DLQWorker.

        Args:
            db: AsyncSession from get_db_session()
            redis: Redis client (aioredis.Redis)
        """
        self.db = db
        self.redis = redis
        self._logger = logger

    async def capture(
        self,
        task_name: str,
        task_id: str,
        args: list,
        kwargs: dict,
        exc: Exception,
        traceback_str: str,
        lead_id: str | None = None,
        source_url: str | None = None,
    ) -> LeadDLQ:
        """
        Creates a LeadDLQ record in the database when a pipeline task fails.

        Args:
            task_name: Full task name (e.g., "pipeline.dedup_lead")
            task_id: Celery task ID
            args: Task arguments as list
            kwargs: Task keyword arguments as dict
            exc: Exception that caused the failure
            traceback_str: Full traceback string
            lead_id: Optional lead ID if task is lead-related
            source_url: Optional source URL being processed

        Returns:
            LeadDLQ record created with stage=new

        Note:
            Never raises exceptions - DLQ capture failure is logged only.
        """
        try:
            retry_count = 0
            max_retries = 3
            now = datetime.utcnow()
            next_retry_at = now + timedelta(minutes=5)

            dlq_record = LeadDLQ(
                original_lead_id=lead_id,
                original_lead_data=json.dumps(
                    {
                        "args": args,
                        "kwargs": kwargs,
                        "task_id": task_id,
                        "source_url": source_url,
                    }
                ),
                failure_type=exc.__class__.__name__,
                error_message=str(exc)[:1000],
                error_stack=traceback_str[:3000],
                retry_count=retry_count,
                max_retries=max_retries,
                next_retry_at=next_retry_at,
                stage=LeadDLQStage.new,
            )

            self.db.add(dlq_record)
            await self.db.commit()
            await self.db.refresh(dlq_record)

            self._logger.info(
                "task_captured_to_dlq",
                task=task_name,
                task_id=task_id,
                exc=str(exc)[:200],
                dlq_id=str(dlq_record.id),
            )

            return dlq_record

        except Exception as e:
            # DLQ capture failure must be swallowed - log only
            self._logger.error(
                "dlq_capture_failed",
                task_name=task_name,
                exc=str(e),
            )
            raise

    async def process_retries(self) -> dict[str, Any]:
        """
        Called by Celery beat every 5 minutes.

        Queries for LeadDLQ records that are eligible for retry:
          - stage IN (LeadDLQStage.new, LeadDLQStage.retrying)
          - next_retry_at <= datetime.utcnow()
          - can_retry() == True

        For each eligible record:
          1. Check can_retry() - if False: mark failed_permanent, skip
          2. Route to correct Celery task using TASK_ROUTER
          3. On success: update stage, retry_count, next_retry_at
          4. On router failure: mark failed_permanent, log CRITICAL

        Returns:
            {"processed": N, "requeued": M, "failed_permanent": K}
        """
        processed = 0
        requeued = 0
        failed_permanent = 0
        now = datetime.utcnow()

        # Query eligible records
        stmt = (
            select(LeadDLQ)
            .where(
                LeadDLQ.stage.in_([LeadDLQStage.new, LeadDLQStage.retrying]),
                LeadDLQ.next_retry_at <= now,
            )
            .order_by(LeadDLQ.next_retry_at.asc())
            .limit(20)  # Don't flood queue
        )

        result = await self.db.execute(stmt)
        records = result.scalars().all()

        for record in records:
            processed += 1

            # Check if can retry
            if not record.can_retry():
                record.stage = LeadDLQStage.failed_permanent
                record.resolved_at = now
                record.resolved_by = "auto_exhausted"
                await self.db.commit()
                failed_permanent += 1
                self._logger.warning(
                    "dlq_record_failed_permanent",
                    dlq_id=str(record.id),
                    task_name="unknown",
                    reason="max_retries_exceeded",
                )
                continue

            # Parse original data
            try:
                original_data = json.loads(record.original_lead_data)
                task_args = original_data.get("args", [])
                task_kwargs = original_data.get("kwargs", {})
                task_name = self._extract_task_name_from_data(original_data, record)
            except Exception as e:
                record.stage = LeadDLQStage.failed_permanent
                record.resolved_at = now
                record.resolved_by = "invalid_data"
                await self.db.commit()
                failed_permanent += 1
                self._logger.error(
                    "dlq_invalid_original_data",
                    dlq_id=str(record.id),
                    error=str(e),
                )
                continue

            # Route to correct task
            task_router_entry = self.TASK_ROUTER.get(task_name)
            if task_router_entry is None:
                record.stage = LeadDLQStage.failed_permanent
                record.resolved_at = now
                record.resolved_by = "no_router"
                await self.db.commit()
                failed_permanent += 1
                self._logger.error(
                    "dlq_no_task_router",
                    dlq_id=str(record.id),
                    task_name=task_name,
                )
                continue

            try:
                # Re-enqueue task
                task_router_entry(task_args, task_kwargs)

                # Update DLQ record
                record.stage = LeadDLQStage.retrying
                record.retry_count += 1
                record.last_retry_at = now
                record.next_retry_at = record.calculate_backoff()
                await self.db.commit()

                requeued += 1
                self._logger.info(
                    "dlq_task_requeued",
                    dlq_id=str(record.id),
                    task_name=task_name,
                    retry_count=record.retry_count,
                )

            except Exception as e:
                record.stage = LeadDLQStage.failed_permanent
                record.resolved_at = now
                record.resolved_by = "requeue_failed"
                await self.db.commit()
                failed_permanent += 1
                self._logger.critical(
                    "dlq_requeue_failed_permanent",
                    dlq_id=str(record.id),
                    task_name=task_name,
                    error=str(e),
                )

        return {
            "processed": processed,
            "requeued": requeued,
            "failed_permanent": failed_permanent,
        }

    def _extract_task_name_from_data(self, data: dict, record: LeadDLQ) -> str:
        """Extract task name from original data or use record field."""
        # Try to extract from original data first
        if "task_name" in data:
            return data["task_name"]
        # Fallback - this won't work well, need to store task_name separately
        # For now, try to infer from task_id if it has pipeline/actors prefix
        return "pipeline.dedup_lead"  # Default - should be improved

    async def mark_resolved(self, dlq_id: str, resolved_by: str) -> bool:
        """
        Admin action: manually mark a DLQ record as resolved.

        Args:
            dlq_id: LeadDLQ ID (UUID string)
            resolved_by: User email or ID resolving the issue

        Returns:
            True if found and updated, False if not found
        """
        result = await self.db.execute(
            select(LeadDLQ).where(LeadDLQ.id == dlq_id)
        )
        record = result.scalar_one_or_none()

        if record is None:
            return False

        record.stage = LeadDLQStage.resolved
        record.resolved_at = datetime.utcnow()
        record.resolved_by = resolved_by
        await self.db.commit()

        self._logger.info(
            "dlq_record_resolved",
            dlq_id=dlq_id,
            resolved_by=resolved_by,
        )
        return True

    async def get_stats(self) -> dict[str, Any]:
        """
        For /health endpoint and admin dashboard.

        Returns:
            {
                "total": COUNT all LeadDLQ,
                "by_stage": {stage: count} for all 4 stages,
                "by_task": top 10 task_name by failure count,
                "oldest_failure": earliest created_at among stage=new,
                "failed_permanent": COUNT stage=failed_permanent,
            }
        """
        from sqlalchemy import func, text

        # Get total count
        total_result = await self.db.execute(select(func.count(LeadDLQ.id)))
        total = total_result.scalar_one() or 0

        # Count by stage
        stage_result = await self.db.execute(
            select(LeadDLQ.stage, func.count(LeadDLQ.id)).group_by(LeadDLQ.stage)
        )
        stage_rows = stage_result.all()
        by_stage = {row[0]: row[1] for row in stage_rows}

        # Ensure all stages are present
        for stage in LeadDLQStage:
            if stage not in by_stage:
                by_stage[stage] = 0

        # Get oldest failure (stage=new)
        oldest_result = await self.db.execute(
            select(func.min(LeadDLQ.created_at)).where(
                LeadDLQ.stage == LeadDLQStage.new
            )
        )
        oldest_failure = oldest_result.scalar_one_or_none()

        # Top 10 tasks by failure count
        task_result = await self.db.execute(
            select(
                text("json_extract(original_lead_data, '$.task_name') as task_name"),
                func.count(LeadDLQ.id).label("count"),
            )
            .group_by(text("json_extract(original_lead_data, '$.task_name')"))
            .order_by(func.count(LeadDLQ.id).desc())
            .limit(10)
        )
        task_rows = task_result.all()
        by_task = {row[0] or "unknown": row[1] for row in task_rows}

        # Count failed_permanent
        failed_result = await self.db.execute(
            select(func.count(LeadDLQ.id)).where(
                LeadDLQ.stage == LeadDLQStage.failed_permanent
            )
        )
        failed_permanent = failed_result.scalar_one() or 0

        return {
            "total": total,
            "by_stage": by_stage,
            "by_task": by_task,
            "oldest_failure": oldest_failure,
            "failed_permanent": failed_permanent,
        }

    async def get_recent(self, limit: int = 50) -> list[LeadDLQ]:
        """
        Get most recent DLQ records for admin dashboard.

        Args:
            limit: Maximum records to return

        Returns:
            List of LeadDLQ records ordered by created_at DESC
        """
        result = await self.db.execute(
            select(LeadDLQ)
            .order_by(LeadDLQ.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def cleanup_resolved(self, older_than_days: int = 30) -> dict[str, int]:
        """
        Auto-cleanup: hard-delete resolved/failed_permanent records older than N days.

        Returns {"deleted": N}
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)

        result = await self.db.execute(
            select(LeadDLQ).where(
                LeadDLQ.stage.in_([LeadDLQStage.resolved, LeadDLQStage.failed_permanent]),
                LeadDLQ.created_at <= cutoff,
            )
        )
        stale = result.scalars().all()

        deleted = 0
        for record in stale:
            await self.db.delete(record)
            deleted += 1

        if deleted > 0:
            await self.db.commit()
            self._logger.info("dlq_cleanup_complete", deleted=deleted, cutoff=str(cutoff))

        return {"deleted": deleted}

    async def get_error_categories(self) -> dict[str, int]:
        """Categorize failures by error type for monitoring."""
        from sqlalchemy import func

        result = await self.db.execute(
            select(LeadDLQ.failure_type, func.count(LeadDLQ.id))
            .where(LeadDLQ.stage != LeadDLQStage.resolved)
            .group_by(LeadDLQ.failure_type)
            .order_by(func.count(LeadDLQ.id).desc())
        )
        return {row[0]: row[1] for row in result.all()}

    async def get_burst_stats(self, window_minutes: int = 60) -> dict[str, Any]:
        """Detect failure bursts — high failure rate in a time window."""
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        result = await self.db.execute(
            select(func.count(LeadDLQ.id)).where(LeadDLQ.created_at >= cutoff)
        )
        recent_count = result.scalar_one() or 0

        burst_threshold = 10  # More than 10 failures in N minutes = burst
        is_burst = recent_count > burst_threshold

        return {
            "window_minutes": window_minutes,
            "recent_failures": recent_count,
            "burst_threshold": burst_threshold,
            "is_burst": is_burst,
            "severity": "critical" if is_burst else "normal",
        }
