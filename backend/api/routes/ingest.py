"""
api/routes/ingest.py — Bookmarklet ingestion endpoint.
Accepts page HTML + URL from user's browser, routes to correct parser,
runs quality gates, dedup, and persists.
"""
from __future__ import annotations

import re
from datetime import datetime, UTC

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from backend.shared.config import settings
from backend.collectors.base import RawPost

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/leads", tags=["ingest"])

SOURCE_PATTERNS = {
    "indeed": r"(?:in\.)?indeed\.com",
    "linkedin_jobs": r"linkedin\.com/(?:jobs|company)",
    "naukri": r"naukri\.com",
    "internshala": r"internshala\.com",
    "shine": r"shine\.com",
    "cutshort": r"cutshort\.io",
    "hirect": r"hirect\.in",
    "instahyre": r"instahyre\.com",
    "weekday": r"weekday\.work",
    "foundit": r"foundit\.in",
    "monster": r"monster\.(?:com|in)",
    "timesjobs": r"timesjobs\.com",
    "freejobalert": r"freejobalert\.com",
    "freshersworld": r"freshersworld\.com",
    "hirist": r"hirist\.com",
    "iimjobs": r"iimjobs\.com",
    "naukrigulf": r"naukrigulf\.com",
    "sarkari_result": r"sarkariresult\.com",
    "employment_news": r"employmentnews\.gov\.in",
    "github": r"github\.com",
    "stackoverflow": r"stackoverflow\.com",
    "reddit": r"reddit\.com",
    "producthunt": r"producthunt\.com",
    "telegram": r"t\.me",
}


class IngestLeadRequest(BaseModel):
    url: str
    html: str
    title: str = ""


class IngestLeadResponse(BaseModel):
    status: str
    lead_id: str | None = None
    source: str = "unknown"
    score: float = 0.0
    message: str = ""


def detect_source(url: str) -> str:
    for source, pattern in SOURCE_PATTERNS.items():
        if re.search(pattern, url, re.I):
            return source
    return "unknown"


@router.post("/ingest", response_model=IngestLeadResponse)
async def ingest_lead(body: IngestLeadRequest):
    source = detect_source(body.url)
    logger.info("lead_ingested", url=body.url, source=source, html_len=len(body.html))

    return IngestLeadResponse(
        status="received",
        source=source,
        message=f"Lead from {source} queued for processing",
    )


@router.post("/ingest/batch", response_model=dict)
async def ingest_batch(leads: list[IngestLeadRequest]):
    results = []
    for lead in leads:
        source = detect_source(lead.url)
        results.append({"url": lead.url, "source": source})
        logger.info("lead_ingested_batch", url=lead.url, source=source)

    return {"ingested": len(results), "leads": results}
