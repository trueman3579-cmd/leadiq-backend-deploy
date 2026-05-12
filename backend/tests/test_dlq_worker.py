"""
tests/test_dlq_worker.py — Tests for DLQ worker.

Tests DLQWorker.capture(), process_retries(), mark_resolved(), and get_stats().
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.workers.dlq import DLQWorker
from backend.models.lead_dlq import LeadDLQ, LeadDLQStage


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=None)
    return redis


@pytest.fixture
def dlq_worker(mock_db: Any, mock_redis: Any):
    """Create a DLQWorker instance with mocked dependencies."""
    return DLQWorker(mock_db, mock_redis)


@pytest.mark.asyncio
async def test_capture_creates_db_record(dlq_worker: DLQWorker):
    """Test that capture() creates a LeadDLQ record with correct fields."""
    from datetime import datetime

    with patch("backend.workers.dlq.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = datetime(2026, 4, 5, 12, 0, 0)
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        result = await dlq_worker.capture(
            task_name="pipeline.dedup_lead",
            task_id="task-123",
            args=["lead-456"],
            kwargs={},
            exc=ValueError("Test error"),
            traceback_str="Traceback (most recent call last)...",
            lead_id="lead-456",
            source_url="https://example.com",
        )

        assert result is not None
        assert result.stage == LeadDLQStage.new
        assert result.retry_count == 0
        assert result.failure_type == "ValueError"
        assert result.error_message == "Test error"

        # Verify record was added to DB
        dlq_worker.db.add.assert_called_once()
        dlq_worker.db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_retries_requeues_eligible(dlq_worker: DLQWorker):
    """Test process_retries() re-queues eligible DLQ records."""
    # Create mock records that can retry
    now = datetime.utcnow()
    records = [
        LeadDLQ(
            id="1",
            original_lead_data=json.dumps(
                {"args": [], "kwargs": {}, "task_name": "pipeline.dedup_lead"}
            ),
            failure_type="ValueError",
            retry_count=0,
            max_retries=3,
            stage=LeadDLQStage.new,
            next_retry_at=now - timedelta(minutes=1),
        ),
        LeadDLQ(
            id="2",
            original_lead_data=json.dumps(
                {"args": [], "kwargs": {}, "task_name": "pipeline.dedup_lead"}
            ),
            failure_type="ValueError",
            retry_count=0,
            max_retries=3,
            stage=LeadDLQStage.new,
            next_retry_at=now - timedelta(minutes=1),
        ),
    ]

    # Mock the DB query
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = records
    dlq_worker.db.execute = AsyncMock(return_value=mock_result)

    # Mock task router
    mock_task_func = MagicMock()
    dlq_worker.TASK_ROUTER = {"pipeline.dedup_lead": mock_task_func}

    # Run process_retries
    result = await dlq_worker.process_retries()

    assert result["processed"] == 2
    assert result["requeued"] == 2
    assert result["failed_permanent"] == 0

    # Verify records were updated
    for record in records:
        assert record.stage == LeadDLQStage.retrying
        assert record.retry_count == 1
        assert record.last_retry_at is not None


@pytest.mark.asyncio
async def test_process_retries_marks_permanent_when_no_retry(dlq_worker: DLQWorker):
    """Test process_retries() marks records as failed_permanent when can_retry() is False."""
    now = datetime.utcnow()
    records = [
        LeadDLQ(
            id="1",
            original_lead_data=json.dumps(
                {"args": [], "kwargs": {}, "task_name": "pipeline.dedup_lead"}
            ),
            failure_type="ValueError",
            retry_count=3,  # Already at max retries
            max_retries=3,
            stage=LeadDLQStage.new,
            next_retry_at=now - timedelta(minutes=1),
        ),
    ]

    # Mock the DB query
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = records
    dlq_worker.db.execute = AsyncMock(return_value=mock_result)

    # Run process_retries
    result = await dlq_worker.process_retries()

    assert result["processed"] == 1
    assert result["requeued"] == 0
    assert result["failed_permanent"] == 1

    for record in records:
        assert record.stage == LeadDLQStage.failed_permanent
        assert record.resolved_by == "auto_exhausted"


@pytest.mark.asyncio
async def test_mark_resolved(dlq_worker: DLQWorker):
    """Test mark_resolved() updates the record correctly."""
    record = LeadDLQ(
        id="test-id",
        original_lead_data=json.dumps({}),
        failure_type="ValueError",
    )
    dlq_worker.db.add = MagicMock()
    dlq_worker.db.commit = AsyncMock()

    # Mock the DB execute to return the record
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = record
    dlq_worker.db.execute = AsyncMock(return_value=mock_result)

    success = await dlq_worker.mark_resolved("test-id", "admin@example.com")

    assert success is True
    assert record.stage == LeadDLQStage.resolved
    assert record.resolved_by == "admin@example.com"
    assert record.resolved_at is not None


@pytest.mark.asyncio
async def test_get_stats_returns_all_stages(dlq_worker: DLQWorker):
    """Test get_stats() returns counts for all stages."""
    # Build a list of mock results for each sequential db.execute() call
    # 1. total count, 2. stage counts, 3. oldest failure, 4. task counts
    total_result = MagicMock()
    total_result.scalar_one.return_value = 20

    stage_result = MagicMock()
    stage_result.all.return_value = [
        (LeadDLQStage.new, 5),
        (LeadDLQStage.retrying, 2),
        (LeadDLQStage.failed_permanent, 3),
        (LeadDLQStage.resolved, 10),
    ]

    oldest_result = MagicMock()
    oldest_result.scalar_one_or_none.return_value = datetime.utcnow() - timedelta(hours=1)

    task_result = MagicMock()
    task_result.all.return_value = [
        ("pipeline.dedup_lead", 15),
        ("pipeline.collect_and_publish", 5),
    ]

    failed_result = MagicMock()
    failed_result.scalar_one.return_value = 3

    dlq_worker.db.execute = AsyncMock(side_effect=[
        total_result, stage_result, oldest_result, task_result, failed_result,
    ])

    stats = await dlq_worker.get_stats()

    assert stats["total"] == 20
    assert stats["by_stage"][LeadDLQStage.new] == 5
    assert stats["by_stage"][LeadDLQStage.retrying] == 2
    assert stats["by_stage"][LeadDLQStage.failed_permanent] == 3
    assert stats["by_stage"][LeadDLQStage.resolved] == 10
    assert stats["failed_permanent"] == 3


@pytest.mark.asyncio
async def test_get_recent_returns_latest_records(dlq_worker: DLQWorker):
    """Test get_recent() returns the most recent records."""
    records = [
        LeadDLQ(id="1", original_lead_data=json.dumps({}), failure_type="ValueError"),
        LeadDLQ(id="2", original_lead_data=json.dumps({}), failure_type="ValueError"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = records
    dlq_worker.db.execute = AsyncMock(return_value=mock_result)

    result = await dlq_worker.get_recent(limit=50)

    assert len(result) == 2
    dlq_worker.db.execute.assert_called_once()
