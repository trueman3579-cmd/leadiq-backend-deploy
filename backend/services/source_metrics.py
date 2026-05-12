"""
source_metrics.py — Per-source quality dashboard metrics.

Track requests, successful pages, blocked pages, parser errors, timeout rate,
active/expired links, web-dev hits, conversion score average, posts published.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SourceMetrics:
    source: str
    requests: int = 0
    successful_pages: int = 0
    blocked_pages: int = 0
    parser_errors: int = 0
    timeouts: int = 0
    active_links: int = 0
    expired_links: int = 0
    uncertain_links: int = 0
    web_dev_hits: int = 0
    conversion_score_sum: float = 0.0
    conversion_score_count: int = 0
    posts_published: int = 0
    total_response_time_ms: float = 0.0
    _last_reset: float = field(default_factory=time.time)

    @property
    def timeout_rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.timeouts / self.requests

    @property
    def success_rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.successful_pages / self.requests

    @property
    def avg_conversion_score(self) -> float:
        if self.conversion_score_count == 0:
            return 0.0
        return self.conversion_score_sum / self.conversion_score_count

    @property
    def avg_response_time_ms(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.total_response_time_ms / self.requests

    def record_request(self, success: bool, blocked: bool = False,
                       timeout: bool = False, parser_error: bool = False,
                       response_time_ms: float = 0.0):
        self.requests += 1
        if success:
            self.successful_pages += 1
        if blocked:
            self.blocked_pages += 1
        if timeout:
            self.timeouts += 1
        if parser_error:
            self.parser_errors += 1
        self.total_response_time_ms += response_time_ms

    def record_liveness(self, status: str):
        if status == "live":
            self.active_links += 1
        elif status == "dead":
            self.expired_links += 1
        elif status == "uncertain":
            self.uncertain_links += 1

    def record_web_dev_hit(self):
        self.web_dev_hits += 1

    def record_conversion_score(self, score: float):
        self.conversion_score_sum += score
        self.conversion_score_count += 1

    def record_published(self):
        self.posts_published += 1

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "requests": self.requests,
            "successful_pages": self.successful_pages,
            "blocked_pages": self.blocked_pages,
            "parser_errors": self.parser_errors,
            "timeouts": self.timeouts,
            "timeout_rate": round(self.timeout_rate, 3),
            "success_rate": round(self.success_rate, 3),
            "active_links": self.active_links,
            "expired_links": self.expired_links,
            "uncertain_links": self.uncertain_links,
            "web_dev_hits": self.web_dev_hits,
            "avg_conversion_score": round(self.avg_conversion_score, 3),
            "posts_published": self.posts_published,
            "avg_response_time_ms": round(self.avg_response_time_ms, 1),
        }


class MetricsCollector:
    def __init__(self):
        self._metrics: dict[str, SourceMetrics] = defaultdict(
            lambda: SourceMetrics(source="unknown")
        )

    def for_source(self, source: str) -> SourceMetrics:
        if source not in self._metrics:
            self._metrics[source] = SourceMetrics(source=source)
        return self._metrics[source]

    def record(self, source: str, **kwargs):
        self.for_source(source).record_request(**kwargs)

    def summary(self) -> dict[str, dict]:
        return {s: m.to_dict() for s, m in sorted(self._metrics.items())}


_global_collector = MetricsCollector()


def get_metrics() -> MetricsCollector:
    return _global_collector
