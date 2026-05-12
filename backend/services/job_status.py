"""
job_status.py — Job URL liveness status taxonomy.

Merged from sherlock (sherlock_project/result.py) QueryStatus enum.
Maps username-probe taxonomy → job-probe taxonomy.
"""
from __future__ import annotations

from enum import Enum


class JobStatus(Enum):
    LIVE = "live"
    DEAD = "dead"
    UNCERTAIN = "uncertain"
    INVALID = "invalid"
    BLOCKED = "blocked"

    def __str__(self) -> str:
        return self.value


class JobResult:
    __slots__ = ("job_id", "source", "url", "status", "query_time", "context")

    def __init__(
        self,
        job_id: str,
        source: str,
        url: str,
        status: JobStatus,
        query_time: float | None = None,
        context: str | None = None,
    ):
        self.job_id = job_id
        self.source = source
        self.url = url
        self.status = status
        self.query_time = query_time
        self.context = context

    def __str__(self) -> str:
        s = str(self.status)
        if self.context:
            s += f" ({self.context})"
        return s

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "source": self.source,
            "url": self.url,
            "status": self.status.value,
            "query_time": self.query_time,
            "context": self.context,
        }
