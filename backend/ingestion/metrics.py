"""
ingestion/metrics.py — Ingestion metrics tracking.

Tracks and reports ingestion pipeline metrics for monitoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import structlog


@dataclass
class IngestionMetrics:
    """Metrics for lead ingestion pipeline."""

    published: int = 0
    skipped: int = 0
    failed: int = 0
    sources: list[str] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def total_collected(self) -> int:
        """Total posts collected (published + skipped)."""
        return self.published + self.skipped

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        total = self.total_collected
        if total == 0:
            return 0.0
        return (self.published / total) * 100

    @property
    def duration_seconds(self) -> float:
        """Duration of ingestion in seconds."""
        if not self.start_time or not self.end_time:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "date": date.today().isoformat(),
            "published": self.published,
            "skipped": self.skipped,
            "failed": self.failed,
            "total_collected": self.total_collected,
            "success_rate": round(self.success_rate, 2),
            "sources": self.sources,
            "duration_seconds": round(self.duration_seconds, 2),
        }

    def record_source(self, source: str) -> None:
        """Record that a source was processed."""
        if source not in self.sources:
            self.sources.append(source)

    def start(self) -> None:
        """Mark ingestion start time."""
        self.start_time = datetime.now()

    def finish(self) -> None:
        """Mark ingestion end time."""
        self.end_time = datetime.now()


logger = structlog.get_logger("ingestion.metrics")


class MetricsLogger:
    """Logger for ingestion metrics with integration to external services."""

    def __init__(self) -> None:
        self._metrics = IngestionMetrics()
        self._enabled = True

    def log(self, metrics: IngestionMetrics | None = None) -> dict[str, Any]:
        """
        Log current metrics.

        Args:
            metrics: Optional metrics to log (uses internal if not provided)

        Returns:
            Logged metrics dictionary
        """
        m = metrics or self._metrics
        log_data = m.to_dict()

        logger.info("ingestion_complete", **log_data)

        # Publish to Sentry if available
        try:
            import sentry_sdk
            sentry_sdk.capture_message("ingestion_complete", level="info", extras=log_data)
        except ImportError:
            pass

        return log_data

    def reset(self) -> None:
        """Reset metrics for new ingestion run."""
        self._metrics = IngestionMetrics()
