"""
backend/services/waterfall_enrichment.py — Waterfall Enrichment Pipeline

Enriches leads through a multi-tier fallback strategy:
  1. Hunter.io → Email extraction (25/day free tier)
  2. Clearbit → Company data enrichment
  3. Gemini → Final fallback for any missing data

Redis quota guards track daily API usage to prevent hitting limits.

Usage:
    from backend.services.waterfall_enrichment import enrich_lead

    enriched = await enrich_lead(lead_data, session)
"""
from __future__ import annotations

import structlog
from datetime import datetime, UTC
from typing import Any

from backend.shared.config import settings
from backend.shared.stream import redis_stream
from backend.llm.gemini_service import extract_lead

logger = structlog.get_logger()


def _now_iso() -> str:
    """Get current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


# ── Enrichment Tier Configuration ────────────────────────────────────────────────

# Free tier API quotas
DAILY_QUOTAS = {
    "hunter": 25,      # Hunter.io email finder: 25 free requests/day
    "clearbit": 50,    # Clearbit Enrichment: 50 free requests/day
}


# ── Quota Management ────────────────────────────────────────────────────────────

async def check_quota(api_name: str) -> bool:
    """
    Check if quota is available for the specified API.

    Args:
        api_name: API identifier (hunter, clearbit)

    Returns:
        True if quota available, False if exhausted
    """
    r = redis_stream._r if redis_stream._r else None
    if r is None:
        # Fail-open: allow if Redis not connected
        return True

    try:
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"enrich:quota:{api_name}:{today}"
        used = int(await r.get(key) or 0)

        if used >= DAILY_QUOTAS.get(api_name, 100):
            logger.warning("enrichment_quota_exhausted", api=api_name, used=used)
            return False

        # Increment quota
        await r.incr(key)
        await r.expire(key, 86400)  # 24-hour TTL
        return True

    except Exception as exc:
        logger.error("enrichment_quota_check_error", api=api_name, error=str(exc))
        return True  # Fail-open


async def record_usage(api_name: str, count: int = 1) -> None:
    """Record API usage for quota tracking."""
    r = redis_stream._r if redis_stream._r else None
    if r is None:
        return

    try:
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"enrich:quota:{api_name}:{today}"
        await r.incrby(key, count)
        await r.expire(key, 86400)
        logger.info("enrichment_quota_recorded", api=api_name, used=count)
    except Exception as exc:
        logger.error("enrichment_quota_record_error", api=api_name, error=str(exc))


# ── Hunter.io Email Enrichment ───────────────────────────────────────────────────

async def enrich_with_hunter(email_domain: str, company_name: str | None = None) -> dict[str, Any] | None:
    """
    Attempt email extraction using Hunter.io API.

    Free tier: 25 requests/day

    Args:
        email_domain: Company domain to search
        company_name: Optional company name for better matching

    Returns:
        Enriched data with email if found, None if quota exhausted or API unavailable
    """
    if not await check_quota("hunter"):
        logger.info("enrichment_hunter_quota_exhausted", domain=email_domain)
        return None

    try:
        import aiohttp

        api_key = settings.HUNTER_API_KEY
        if not api_key:
            logger.info("enrichment_hunter_no_api_key", domain=email_domain)
            return None

        # Construct Hunter.io API URL
        # Endpoint: https://api.hunter.io/v2/email-finder?domain={domain}
        async with aiohttp.ClientSession() as session:
            params = {"domain": email_domain, "api_key": api_key}
            if company_name:
                params["company"] = company_name

            async with session.get(
                "https://api.hunter.io/v2/email-finder",
                params=params,
                timeout=15.0
            ) as response:
                if response.status == 429:
                    logger.warning("enrichment_hunter_rate_limited", domain=email_domain)
                    return None

                data = await response.json()

                if response.status != 200 or "data" not in data:
                    logger.warning("enrichment_hunter_no_email", domain=email_domain, status=response.status)
                    return None

                email_data = data.get("data", {})

                # Record usage
                await record_usage("hunter")

                return {
                    "email": email_data.get("email"),
                    "email_type": email_data.get("type"),
                    "confidence": email_data.get("score"),
                    "source": "hunter_io",
                    "enriched_at": _now_iso(),
                }

    except ImportError:
        logger.warning("enrichment_hunter_aiohttp_missing")
        return None
    except Exception as exc:
        logger.error("enrichment_hunter_error", domain=email_domain, error=str(exc))
        return None


# ── Clearbit Company Enrichment ──────────────────────────────────────────────────

async def enrich_with_clearbit(domain: str) -> dict[str, Any] | None:
    """
    Enrich company data using Clearbit API.

    Free tier: 50 requests/day

    Args:
        domain: Company domain to enrich

    Returns:
        Enriched company data if found, None if quota exhausted or API unavailable
    """
    if not await check_quota("clearbit"):
        logger.info("enrichment_clearbit_quota_exhausted", domain=domain)
        return None

    try:
        import aiohttp

        api_key = settings.CLEARBIT_API_KEY
        if not api_key:
            logger.info("enrichment_clearbit_no_api_key", domain=domain)
            return None

        # Clearbit Enrichment API
        # Endpoint: https://company-stream.clearbit.com/v2/companies/find?domain={domain}
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {api_key}"}
            params = {"domain": domain}

            async with session.get(
                "https://company-stream.clearbit.com/v2/companies/find",
                headers=headers,
                params=params,
                timeout=15.0
            ) as response:
                if response.status == 429:
                    logger.warning("enrichment_clearbit_rate_limited", domain=domain)
                    return None

                if response.status == 404:
                    # Company not found in Clearbit
                    await record_usage("clearbit")
                    return None

                data = await response.json()

                if response.status != 200:
                    logger.warning("enrichment_clearbit_error", domain=domain, status=response.status)
                    return None

                # Record usage
                await record_usage("clearbit")

                # Map Clearbit data to our schema
                return {
                    "company_name": data.get("name"),
                    "industry": data.get("category", {}).get("sector"),
                    "company_size": _map_clearbit_size(data.get("employs")),
                    "location": data.get("location"),
                    "website": data.get("domain"),
                    "funding_stage": _map_clearbit_funding(data.get("funding")),
                    "tech_stack": data.get("techstack", [])[:10],  # Top 10 tech
                    "description": data.get("description"),
                    "source": "clearbit",
                    "enriched_at": _now_iso(),
                }

    except ImportError:
        logger.warning("enrichment_clearbit_aiohttp_missing")
        return None
    except Exception as exc:
        logger.error("enrichment_clearbit_error", domain=domain, error=str(exc))
        return None


def _map_clearbit_size(employs: int | None) -> str | None:
    """Map Clearbit employee count to our size buckets."""
    if employs is None:
        return None
    if employs < 11:
        return "1-10"
    elif employs < 51:
        return "11-50"
    elif employs < 201:
        return "51-200"
    elif employs < 501:
        return "201-500"
    else:
        return "500+"


def _map_clearbit_funding(status: str | None) -> str | None:
    """Map Clearbit funding status to our stages."""
    if status is None:
        return None
    mapping = {
        "seed": "seed",
        "angel": "pre-seed",
        "series_a": "series-a",
        "series_b": "series-b",
        "series_c": "series-c",
        "ipo": "public",
        "private": None,  # Unknown stage
    }
    return mapping.get(status)


# ── Gemini Fallback Enrichment ───────────────────────────────────────────────────

async def enrich_with_gemini(
    content: str,
    source: str,
    url: str,
) -> dict[str, Any] | None:
    """
    Final fallback: Use Gemini LLM to extract data from content.

    Args:
        content: Page content to extract from
        source: Source identifier
        url: Original URL

    Returns:
        Extracted lead data or None if budget exhausted
    """
    try:
        result = await extract_lead(content, source, url)
        if "error" in result:
            logger.warning("enrichment_gemini_error", source=source, error=result["error"])
            return None
        return result
    except Exception as exc:
        logger.error("enrichment_gemini_error", source=source, error=str(exc))
        return None


# ── Main Waterfall Enrichment Function ───────────────────────────────────────────

async def enrich_lead(
    lead_data: dict[str, Any],
    session: Any = None,
) -> dict[str, Any]:
    """
    Apply waterfall enrichment to a lead.

    Enrichment order:
      1. Hunter.io → Extract email (if domain available)
      2. Clearbit → Enrich company data (if domain available)
      3. Gemini → Extract any remaining missing fields

    Args:
        lead_data: Raw lead data (from collector)
        session: Optional database session for persistence

    Returns:
        Fully enriched lead data
    """
    logger.info(
        "enrichment_start",
        company=lead_data.get("company_name"),
        source=lead_data.get("source"),
    )

    enriched = dict(lead_data)  # Copy input

    # ── Tier 1: Hunter.io Email Extraction ────────────────────────────────────
    domain = None
    if url := enriched.get("url"):
        # Extract domain from URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            domain = None

    if domain:
        hunter_enrich = await enrich_with_hunter(domain, enriched.get("company_name"))
        if hunter_enrich and hunter_enrich.get("email"):
            enriched["email"] = hunter_enrich["email"]
            enriched["enrichment_methods"] = enriched.get("enrichment_methods", []) + ["hunter_io"]
            logger.info("enrichment_hunter_success", email=hunter_enrich["email"])

    # ── Tier 2: Clearbit Company Enrichment ───────────────────────────────────
    if domain:
        clearbit_enrich = await enrich_with_clearbit(domain)
        if clearbit_enrich:
            # Merge clearbit data (only if not already present)
            for field in ["company_name", "industry", "company_size", "location", "website", "funding_stage", "tech_stack"]:
                if not enriched.get(field) and clearbit_enrich.get(field):
                    enriched[field] = clearbit_enrich[field]
            enriched["enrichment_methods"] = enriched.get("enrichment_methods", []) + ["clearbit"]
            logger.info("enrichment_clearbit_success", company=enriched.get("company_name"))

    # ── Tier 3: Gemini Fallback ───────────────────────────────────────────────
    # Check for missing critical fields
    missing_critical = not enriched.get("email") or not enriched.get("industry")

    if missing_critical and enriched.get("url") and enriched.get("body"):
        # Use Gemini to extract from the original content
        content = enriched.get("body", "")
        if len(content) > 100:  # Only enrich if there's meaningful content
            gemini_enrich = await enrich_with_gemini(content, enriched.get("source", ""), enriched.get("url", ""))

            if gemini_enrich:
                # Merge Gemini results (prefer existing values if set)
                for field in ["email", "industry", "company_size", "funding_stage", "tech_stack", "location"]:
                    if not enriched.get(field) and gemini_enrich.get(field):
                        enriched[field] = gemini_enrich[field]

                enriched["enrichment_methods"] = enriched.get("enrichment_methods", []) + ["gemini"]
                logger.info("enrichment_gemini_success", fields_updated=len([f for f in ["email", "industry"] if enriched.get(f)]))

    # Add enrichment metadata
    enriched["enriched_at"] = _now_iso()
    enriched["enrichment_level"] = len(enriched.get("enrichment_methods", []))

    logger.info(
        "enrichment_complete",
        company=enriched.get("company_name"),
        methods=enriched.get("enrichment_methods", []),
        fields_complete=sum(1 for k in ["email", "industry", "company_size"] if enriched.get(k)),
    )

    return enriched


async def batch_enrich_leads(
    leads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Enrich a batch of leads.

    Args:
        leads: List of raw lead data dictionaries

    Returns:
        List of enriched lead data
    """
    return [await enrich_lead(lead) for lead in leads]


__all__ = [
    "enrich_lead",
    "batch_enrich_leads",
    "enrich_with_hunter",
    "enrich_with_clearbit",
    "enrich_with_gemini",
]
