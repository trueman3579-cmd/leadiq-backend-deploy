"""
job_liveness.py — Job URL liveness gate.

Merged from career-ops (check-liveness.mjs).
Classifies URLs as active/expired/uncertain using pattern matching
on page content, URL redirects, and content-length heuristics.
"""
from __future__ import annotations

import re

from backend.services.job_status import JobStatus

EXPIRED_PATTERNS = [
    re.compile(r"job (is )?no longer available", re.I),
    re.compile(r"job.*no longer open", re.I),
    re.compile(r"position has been filled", re.I),
    re.compile(r"this job has expired", re.I),
    re.compile(r"job posting has expired", re.I),
    re.compile(r"no longer accepting applications", re.I),
    re.compile(r"this (position|role|job) (is )?no longer", re.I),
    re.compile(r"this job (listing )?is closed", re.I),
    re.compile(r"job (listing )?not found", re.I),
    re.compile(r"the page you are looking for doesn.t exist", re.I),
    re.compile(r"\d+\s+jobs?\s+found", re.I),
    re.compile(r"search for jobs page is loaded", re.I),
    re.compile(r"diese stelle (ist )?(nicht mehr|bereits) besetzt", re.I),
    re.compile(r"offre (expirée|n'est plus disponible)", re.I),
]

EXPIRED_URL_PATTERNS = [
    re.compile(r"[?&]error=true", re.I),
]

APPLY_PATTERNS = [
    re.compile(r"\bapply\b", re.I),
    re.compile(r"\bsolicitar\b", re.I),
    re.compile(r"\bbewerben\b", re.I),
    re.compile(r"\bpostuler\b", re.I),
    re.compile(r"submit application", re.I),
    re.compile(r"easy apply", re.I),
    re.compile(r"start application", re.I),
    re.compile(r"ich bewerbe mich", re.I),
]

MIN_CONTENT_CHARS = 300


def check_liveness(
    http_status: int,
    body_text: str,
    final_url: str,
) -> tuple[JobStatus, str]:
    if http_status in (404, 410):
        return JobStatus.DEAD, f"HTTP {http_status}"

    for pattern in EXPIRED_URL_PATTERNS:
        if pattern.search(final_url):
            return JobStatus.DEAD, f"redirect: {final_url}"

    if any(p.search(body_text) for p in APPLY_PATTERNS):
        return JobStatus.LIVE, "apply_button_detected"

    for pattern in EXPIRED_PATTERNS:
        match = pattern.search(body_text)
        if match:
            return JobStatus.DEAD, f"pattern: {pattern.pattern}"

    if len(body_text.strip()) < MIN_CONTENT_CHARS:
        return JobStatus.DEAD, "insufficient_content"

    return JobStatus.UNCERTAIN, "content_present_no_apply_button"


def batch_check_liveness(
    results: list[dict],
) -> list[dict]:
    for r in results:
        status, reason = check_liveness(
            http_status=r.get("http_status", 200),
            body_text=r.get("body", ""),
            final_url=r.get("url", ""),
        )
        r["liveness_status"] = status.value
        r["liveness_reason"] = reason
    return results
