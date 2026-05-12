"""
job_classifier.py — 3-tier job URL classification engine.

Merged from sherlock (sherlock_project/sherlock.py:377-451).
Implements message-match, status-code, and response-URL detection tiers
with WAF fingerprint gating — ported from username-probe to job-probe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.services.job_status import JobStatus


@dataclass
class SourceProbeConfig:
    source: str
    url_template: str = ""
    detection_methods: list[str] = field(default_factory=lambda: ["message", "status_code"])
    not_found_indicators: list[str] = field(default_factory=list)
    not_found_codes: list[int] = field(default_factory=lambda: [404, 410])
    redirect_not_found_pattern: str | None = None
    waf_fingerprints: list[str] = field(default_factory=list)
    rate_limit_codes: list[int] = field(default_factory=lambda: [429])
    job_id_regex: str | None = None


DEFAULT_SOURCE_CONFIGS: dict[str, SourceProbeConfig] = {
    "indeed": SourceProbeConfig(
        source="indeed",
        not_found_indicators=["no results", "no jobs found", "we couldn't find any"],
        waf_fingerprints=["challenge-platform", "cf-challenge", "ray id:"],
    ),
    "naukri": SourceProbeConfig(
        source="naukri",
        not_found_indicators=["page not found", "job not found", "no longer accepting"],
        waf_fingerprints=["challenge-platform"],
    ),
    "linkedin_jobs": SourceProbeConfig(
        source="linkedin_jobs",
        not_found_indicators=["page not found", "this job is no longer accepting", "job has expired"],
        redirect_not_found_pattern="/jobs/search/",
        waf_fingerprints=["challenge", "cf-challenge"],
    ),
    "internshala": SourceProbeConfig(
        source="internshala",
        not_found_indicators=["internship not found", "no longer accepting"],
    ),
    "shine": SourceProbeConfig(
        source="shine",
        not_found_indicators=["page not found", "job not available"],
    ),
}


WAF_FINGERPRINTS: list[str] = [
    "challenge-running",
    "challenge-error-text",
    "AwsWafIntegration.forceRefreshToken",
    "perimeterxIdentifiers",
    "cf-challenge",
    "challenge-platform",
]


def classify_job_status(
    http_status: int,
    response_text: str,
    response_url: str,
    config: SourceProbeConfig,
) -> tuple[JobStatus, str | None]:
    context = None

    if any(fp in response_text for fp in (config.waf_fingerprints or WAF_FINGERPRINTS)):
        return JobStatus.BLOCKED, "WAF detected"

    result = JobStatus.UNCERTAIN

    if "message" in config.detection_methods:
        found = any(indicator.lower() in response_text.lower() for indicator in config.not_found_indicators)
        if found:
            result = JobStatus.DEAD
            context = "not_found_indicator_matched"
        else:
            result = JobStatus.LIVE

    if "status_code" in config.detection_methods and result is not JobStatus.DEAD:
        if http_status in config.not_found_codes:
            result = JobStatus.DEAD
            context = f"HTTP {http_status}"
        elif http_status >= 400:
            result = JobStatus.ERROR if http_status in config.rate_limit_codes else JobStatus.UNCERTAIN
            context = f"HTTP {http_status}"
        elif 200 <= http_status < 300:
            result = result or JobStatus.LIVE

    if "response_url" in config.detection_methods and result is not JobStatus.DEAD:
        if config.redirect_not_found_pattern and config.redirect_not_found_pattern in response_url:
            result = JobStatus.DEAD
            context = "redirected_to_search"
        elif 200 <= http_status < 300:
            result = JobStatus.LIVE

    return result, context


def validate_job_id(job_id: str, regex: str | None) -> bool:
    if not regex:
        return True
    return bool(re.search(regex, job_id))
