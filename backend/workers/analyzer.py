"""
workers/analyzer.py — GeminiAnalyzer + 7-stage waterfall pipeline.

IMPORTANT: Keep shared/models.py open alongside this file — Copilot infers
Lead field names and types from there.

The 7-stage waterfall pipeline:
1. Budget Gate - check_budget() before API call
2. Prompt Construction - _build_prompt() with 3-layer architecture
3. Async API Call - asyncio.to_thread() wraps sync Gemini SDK
4. Parse + Validate - AnalyzedLead.model_validate()
5. Audit Stamp - source, source_url, model_used, tokens_used
6. Structured Log - all 8 fields logged (Redis accounting handled by check_budget)
7. Returns AnalyzedLead for persistence to Lead table

This module uses Pydantic v2 AnalyzedLead model exclusively.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from backend.llm.cost_guard import check_budget, consume_budget, queue_for_later
from backend.llm.gemini_service import GeminiExtractionError
from backend.llm.schemas import AnalyzedLead
from backend.llm.SOURCE_PROMPTS import _build_prompt
from backend.shared.config import settings
from backend.shared.stream import redis_stream
from backend.workers.outreach_scorer import gate_outreach
from backend.workers.source_metrics import record_post as record_source_quality

from backend.shared.db import get_db_session
from backend.shared.repository import PostRepo, LeadRepo, QuotaRepo
from hashlib import sha256
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger(__name__)

# ── Retry tracking (event_id → count) ─────────────────────────────────────────
_MAX_RETRIES = 3
_retry_counter: dict[str, int] = {}

def _is_permanent_error(exc: Exception) -> bool:
    """Classify exceptions as permanent (don't retry) or transient (retry)."""
    if isinstance(exc, IntegrityError):
        return True
    if isinstance(exc, GeminiExtractionError):
        return True
    if isinstance(exc, (ValueError, TypeError)):
        return True
    return False

def _record_retry(event_id: str) -> int:
    """Increment retry count and return current count."""
    _retry_counter[event_id] = _retry_counter.get(event_id, 0) + 1
    return _retry_counter[event_id]

def _clear_retry(event_id: str) -> None:
    _retry_counter.pop(event_id, None)

def _prune_retry_counter(max_size: int = 10_000) -> None:
    """Prevent unbounded growth."""
    if len(_retry_counter) > max_size:
        oldest = sorted(_retry_counter.items(), key=lambda x: x[1])[:max_size // 2]
        for k, _ in oldest:
            _retry_counter.pop(k, None)

# ── Async Gemini Wrapper ───────────────────────────────────────────────────────
# The Gemini SDKs (google.generativeai and vertexai) are synchronous.
# Wrap sync calls in asyncio.to_thread() for async compatibility.


async def _call_gemini_async(
    prompt: str,
    model: Any,
) -> tuple[str, int]:
    """
    Call Gemini SDK in thread pool for async compatibility.

    Both google.generativeai and vertexai SDKs are synchronous.
    This wrapper runs them in an executor to avoid blocking the event loop.

    Args:
        prompt: Full prompt string for Gemini
        model: GenerativeModel instance (already initialized)

    Returns:
        (response_text, tokens_used)
    """
    def _sync_call() -> tuple[str, int]:
        response = model.generate_content(prompt)
        tokens_used = len(prompt) // 4 + len(response.text) // 4
        return response.text, tokens_used

    return await asyncio.to_thread(_sync_call)


# ── Prompt constants ──────────────────────────────────────────────────────────
# Multi-mode classifiers — selected based on mode field in stream event.
# Each mode defines different "is_opportunity" criteria and intent taxonomy.

CLASSIFIER_PROMPT = """\
You are a B2B sales intelligence classifier. Analyse the following demand signal.

Signal text: "{text}"
Source: {source}

Return ONLY a valid JSON object — no markdown, no extra text — with exactly these fields:
{{
  "is_opportunity": <true if this is a genuine B2B buying/evaluation signal, else false>,
  "confidence": <float 0.0-1.0 — how confident you are>,
  "intent": "<buy | evaluate | pain | compare | other>",
  "urgency": "<high | medium | low>",
  "reason": "<one sentence explaining your classification>"
}}

Rules:
- is_opportunity = false if: student project, academic question, general discussion, news article
- is_opportunity = true if: buying intent, vendor comparison, pain point with budget hints, hiring for solution
"""

_CLASSIFIER_PROMPTS: dict[str, str] = {
    "b2b_sales": CLASSIFIER_PROMPT,

    "hiring": """\
You are a talent acquisition intelligence classifier. Analyse the following signal.

Signal text: "{text}"
Source: {source}

Return ONLY a valid JSON object with exactly these fields:
{{
  "is_opportunity": <true if this signal shows a company actively hiring or scaling>,
  "confidence": <float 0.0-1.0>,
  "intent": "<hiring_urgent | hiring_planned | company_growth | other>",
  "urgency": "<high | medium | low>",
  "reason": "<one sentence>"
}}

is_opportunity = true if: job posting, "we're hiring", scaling announcement, Series A/B expansion.
intent = hiring_urgent if explicit open roles; hiring_planned if growth/funding signal.
Urgency = high if roles are open now; medium if planned; low if general growth signal.
""",

    "job_search": """\
You are a job market intelligence classifier. Analyse the following signal.

Signal text: "{text}"
Source: {source}

Return ONLY a valid JSON object with exactly these fields:
{{
  "is_opportunity": <true if this is a genuine job opening or strong employer signal>,
  "confidence": <float 0.0-1.0>,
  "intent": "<open_role | company_signal | culture_signal | compensation_signal | other>",
  "urgency": "<high | medium | low>",
  "reason": "<one sentence>"
}}

is_opportunity = true if: job posting, "we are hiring", remote culture signal, equity/comp mention.
Urgency = high if immediate start or closing soon; medium if active hiring; low if general company signal.
""",

    "opportunity": """\
You are a market intelligence analyst detecting emerging business opportunities.

Signal text: "{text}"
Source: {source}

Return ONLY a valid JSON object with exactly these fields:
{{
  "is_opportunity": <true if this reveals a genuine market gap or rising unmet demand>,
  "confidence": <float 0.0-1.0>,
  "intent": "<market_gap | pain_point | trend | emerging_tech | other>",
  "urgency": "<high | medium | low>",
  "reason": "<one sentence>"
}}

is_opportunity = true if: common pain with no good incumbent solution, growing demand, underserved segment.
Urgency = high if multiple people expressing same pain; medium if single strong signal; low if speculative.
""",
}

# ENRICHMENT_PROMPT: extracts company/contact metadata and outreach draft.
# Run only when is_opportunity = true (saves Gemini quota).
ENRICHMENT_PROMPT = """\
You are a B2B sales researcher. A demand signal has been classified as a genuine opportunity.

Signal text: "{text}"
Author: {author}
Source: {source}
Intent: {intent}
Urgency: {urgency}

Return ONLY a valid JSON object — no markdown, no extra text — with:
{{
  "company_name": "<inferred company name or null>",
  "company_size": "<startup | smb | enterprise | unknown>",
  "industry": "<inferred industry vertical or null>",
  "contact_name": "<author's real name if inferrable, else null>",
  "contact_title": "<inferred job title or null>",
  "icp_fit_score": <int 0-100, how well this matches a typical SaaS B2B ICP>,
  "outreach_draft": "<a concise, non-spammy 2-sentence outreach message referencing their specific pain>"
}}
"""

_ENRICHMENT_PROMPTS: dict[str, str] = {
    "b2b_sales": ENRICHMENT_PROMPT,

    "hiring": """\
You are a talent acquisition researcher. A signal indicates a company is hiring.

Signal text: "{text}"
Author: {author}
Source: {source}
Intent: {intent}
Urgency: {urgency}

Return ONLY a valid JSON object with:
{{
  "company_name": "<company or null>",
  "company_size": "<startup | smb | enterprise | unknown>",
  "industry": "<industry vertical or null>",
  "contact_name": "<hiring manager name if visible>",
  "contact_title": "<inferred title of poster>",
  "icp_fit_score": <int 0-100, attractiveness as a hiring target>,
  "outreach_draft": "<brief, specific message to the hiring manager referencing the role>"
}}
""",

    "job_search": """\
You are a career intelligence researcher. Analyse this job opportunity.

Signal text: "{text}"
Author: {author}
Source: {source}

Return ONLY a valid JSON object with:
{{
  "company_name": "<company or null>",
  "company_size": "<startup | smb | enterprise | unknown>",
  "industry": "<industry vertical or null>",
  "contact_name": "<hiring manager if visible>",
  "contact_title": "<role title being hired for>",
  "icp_fit_score": <int 0-100, strength of opportunity>,
  "outreach_draft": "<brief, personalised application message>"
}}
""",

    "opportunity": """\
You are a market opportunity researcher.

Signal text: "{text}"
Author: {author}
Source: {source}

Return ONLY a valid JSON object with:
{{
  "company_name": "<mentioned company or null>",
  "company_size": "<startup | smb | enterprise | unknown>",
  "industry": "<industry vertical or null>",
  "contact_name": "<author name if relevant>",
  "contact_title": null,
  "icp_fit_score": <int 0-100, significance of this market opportunity>,
  "outreach_draft": "<message to the person expressing the pain, offer to co-explore>"
}}
""",
}


# ── GeminiAnalyzer ────────────────────────────────────────────────────────────

class GeminiAnalyzer:
    """
    Analyzes raw posts using Gemini.
    Falls back to deterministic heuristics when no credentials are configured.
    """

    def __init__(self) -> None:
        self._model = None
        self._backend: str = "heuristic"

    def _init_model(self) -> None:
        if self._model is not None:
            return
        try:
            import google.generativeai as genai  # type: ignore

            if settings.GEMINI_API_KEY:
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self._model = genai.GenerativeModel(settings.GEMINI_MODEL)
                self._backend = "gemini-api"
            elif settings.GCP_PROJECT_ID:
                import vertexai  # type: ignore
                from vertexai.generative_models import GenerativeModel  # type: ignore

                vertexai.init(project=settings.GCP_PROJECT_ID, location=settings.GCP_LOCATION)
                self._model = GenerativeModel(settings.GEMINI_MODEL)
                self._backend = "vertex-ai"
            else:
                logger.warning("No Gemini credentials — using heuristic fallback.")
        except ImportError:
            logger.warning("google-generativeai not installed — using heuristic fallback.")

    async def analyze(
        self, text: str, source: str = "", author: str = "", mode: str = "b2b_sales", url: str = ""
    ) -> AnalyzedLead:
        """
        Full analysis: classify → enrich (if opportunity). Returns AnalyzedLead.
        7-stage waterfall pipeline:
        1. Budget Gate - check_budget() before API call
        2. Prompt Construction - _build_prompt() with 3-layer architecture
        3. Async API Call - asyncio.to_thread() wraps sync Gemini SDK
        4. Parse + Validate - AnalyzedLead.model_validate()
        5. Audit Stamp - source, source_url, model_used, tokens_used
        6. Structured Log - all 8 fields logged
        7. Returns AnalyzedLead for persistence to Lead table
        """
        self._init_model()

        # Estimate tokens for budget check
        prompt = _build_prompt(text, source, author, mode)
        estimated_tokens = _estimate_tokens(prompt)

        # Stage 1: Budget Gate
        if not await check_budget(estimated_tokens):
            logger.warning("gemini_budget_exhausted, queuing for later")
            await queue_for_later(
                "analyze_lead",
                {"url": url, "source": source, "text_snippet": text[:500]},
            )
            return self._heuristic_classify(text, mode)

        # Stage 2 & 3: Prompt Construction + Async API Call
        try:
            response_text, tokens_used = await _call_gemini_async(prompt, self._model)

            # Record actual usage after successful Gemini call
            await consume_budget(tokens_used)

            # Stage 4: Parse + Validate
            data = _parse_json(response_text)
            data.update({
                "source": source,
                "source_url": url,
                "model_used": settings.GEMINI_MODEL,
                "tokens_used": tokens_used,
                "analyzed_at": datetime.now(UTC),
            })
            result = AnalyzedLead.model_validate(data)

            # Stage 4.5: Outreach Quality Gate (Day 20)
            if result.outreach_draft:
                gated_draft, specificity_score = gate_outreach(
                    result.outreach_draft, text, result.intent
                )
                result = result.model_copy(update={"outreach_draft": gated_draft})
                if gated_draft is None:
                    logger.info("outreach_refused lead analysis, score=%.2f", specificity_score)

            # Stage 4.6: Record source quality metric (Day 11)
            if source:
                await record_source_quality(source, result.is_opportunity)

            # Stage 5: Audit Stamp (already done in validate)
            # Stage 6: Structured Log
            logger.info(
                "analysis_complete",
                source=source,
                is_opportunity=result.is_opportunity,
                confidence=result.confidence,
                intent=result.intent,
                tokens_used=result.tokens_used,
            )
            return result

        except Exception as exc:
            logger.warning("Gemini API failed, fallback to heuristic: %s", exc)
            return self._heuristic_classify(text, mode)

    def _heuristic_classify(self, text: str, mode: str = "b2b_sales") -> AnalyzedLead:
        """Deterministic fallback when Gemini is unavailable. Mode-aware."""
        text_lower = text.lower()

        is_opportunity = False
        confidence = 0.0
        intent = "other"
        urgency = "low"
        reason = "Heuristic: no match"

        if mode == "hiring":
            hiring_kw = ["hiring", "join our team", "open position", "we're looking for", "apply now"]
            score = sum(1 for kw in hiring_kw if kw in text_lower)
            is_opportunity = score >= 1
            confidence = min(0.4 + score * 0.1, 0.8)
            intent = "hiring_urgent" if score >= 2 else "company_growth"
            urgency = "high" if score >= 2 else "medium"
            reason = "Heuristic: hiring keyword match"
        elif mode == "job_search":
            job_kw = ["software engineer", "developer", "remote", "full-time", "open role", "job"]
            score = sum(1 for kw in job_kw if kw in text_lower)
            is_opportunity = score >= 2
            confidence = min(0.4 + score * 0.1, 0.8)
            intent = "open_role" if score >= 2 else "company_signal"
            urgency = "medium"
            reason = "Heuristic: job signal keyword match"
        elif mode == "opportunity":
            gap_kw = ["nobody", "wish there was", "underserved", "gap", "no good tool", "no solution"]
            score = sum(1 for kw in gap_kw if kw in text_lower)
            is_opportunity = score >= 1
            confidence = min(0.3 + score * 0.15, 0.75)
            intent = "market_gap" if score >= 2 else "pain_point"
            urgency = "high" if score >= 2 else "medium"
            reason = "Heuristic: market gap keyword match"
        else:
            # Default: b2b_sales
            buy_keywords = ["looking for", "recommend", "need", "hiring", "budget", "urgent", "asap"]
            pain_keywords = ["frustrated", "hate", "broken", "switching from", "replacing"]
            score = sum(1 for kw in buy_keywords if kw in text_lower)
            is_opp = score >= 2
            pain = any(kw in text_lower for kw in pain_keywords)
            is_opportunity = is_opp
            confidence = min(0.3 + score * 0.1, 0.8)
            intent = "pain" if pain else ("buy" if is_opp else "other")
            urgency = "high" if "urgent" in text_lower or "asap" in text_lower else "medium"
            reason = "Heuristic match"

        # Return AnalyzedLead with minimal fields - validators will fill in the rest
        return AnalyzedLead(
            is_opportunity=is_opportunity,
            confidence=confidence,
            intent=intent,
            urgency=urgency,
            reason=reason,
            model_used="heuristic",
            tokens_used=0,
            source="",
            source_url="",
            company_name=None,
            company_size=None,
            industry=None,
            contact_name=None,
            contact_title=None,
            icp_fit_score=0.0,
            outreach_draft=None,
            analyzed_at=datetime.now(UTC),
        )


# ── Helper functions for DB writes ───────────────────────────────────────────

def _score_to_band(confidence: float) -> str:
    """Map Gemini confidence to Lead.score_band column value."""
    if confidence >= 0.80:
        return "hot"
    elif confidence >= 0.60:
        return "warm"
    elif confidence >= 0.40:
        return "cool"
    return "cold"


def _content_hash(text: str) -> str:
    """SHA-256 hex of raw post body for dedup."""
    return sha256(text.strip().encode("utf-8")).hexdigest()


# ── Stream consumer entry point ───────────────────────────────────────────────

async def run_analyzer(consumer_name: str = "analyzer-1") -> None:
    """
    Consume lead:collected stream, analyze each post, persist to DB, publish to lead:analyzed.

    Kleppmann ordering: DB commit BEFORE Redis publish.
    If any step fails, the event stays in PEL for DLQ (Day 24).
    """
    analyzer = GeminiAnalyzer()
    group = "analyzers"
    stream = settings.STREAM_COLLECTED

    await redis_stream.ensure_group(stream, group)
    logger.info("analyzer_started", consumer=consumer_name, stream=stream)

    while True:
        events = await redis_stream.consume_group(stream, group, consumer_name, count=5)
        for event in events:
            try:
                # ── BLOCK 1: Field extraction ─────────────────────────────
                text   = event.get("body") or event.get("text") or ""
                source = event.get("source", "")
                author = event.get("author", "")
                mode   = event.get("mode", "b2b_sales")
                url    = event.get("url", "")
                pre_set_post_id = event.get("post_id")

                # ── BLOCK 2: Content guard ────────────────────────────────
                if len(text.strip()) < 20:
                    logger.warning("event_too_short", event_id=event.event_id, length=len(text), source=source)
                    await redis_stream.ack(stream, group, event.event_id)
                    continue

                # ── BLOCK 3: Gemini call (Day 1 work) ────────────────────
                result = await analyzer.analyze(text, source, author, mode, url)

                # ── BLOCK 4: Null result guard → DLQ ─────────────────────
                if result is None:
                    logger.warning("analysis_null_dlq", event_id=event.event_id, source=source, url=url)
                    await redis_stream.xadd("lead:failed", {
                        "event_id": event.event_id,
                        "source": source,
                        "url": url,
                        "reason": "analysis_returned_none",
                        "ts": datetime.now(UTC).isoformat(),
                    })
                    await redis_stream.ack(stream, group, event.event_id)  # Ack after DLQ publish
                    continue

                # ── BLOCK 5: DB writes (PostRepo, LeadRepo, QuotaRepo) ───
                lead = None
                post_id = pre_set_post_id

                async with get_db_session() as session:
                    post_repo = PostRepo(session)
                    lead_repo = LeadRepo(session)
                    quota_repo = QuotaRepo(session)

                    # ── WRITE A: Post row ────────────────────────────────
                    content_hash = _content_hash(text)

                    if post_id is None:
                        already_exists = await post_repo.exists_by_hash(content_hash)

                        if already_exists:
                            # Post already in DB - get its id for lead FK
                            existing = await post_repo.get_by_hash(content_hash)
                            if existing:
                                post_id = existing.id
                            logger.debug("post_dedup_skipped", hash_prefix=content_hash[:16], source=source)
                        else:
                            # Brand new content - write to posts table
                            post = await post_repo.create({
                                "source": source,
                                "external_id": url[:256] if url else content_hash[:32],
                                "url": url,
                                "title": text[:256],
                                "body": text[:10_000],
                                "author": author,
                                "score": int(event.get("score", 0)),
                                "content_hash": content_hash,
                                "raw_meta": {
                                    "mode": mode,
                                    "event_id": event.event_id,
                                    "collected_at": datetime.now(UTC).isoformat(),
                                },
                            })
                            post_id = post.id
                            logger.debug("post_created", post_id=post_id, source=source, hash=content_hash[:16])

                    # ── WRITE B: Lead row ────────────────────────────────
                    lead = await lead_repo.upsert({
                        "post_id": post_id,
                        "is_opportunity": result.is_opportunity,
                        "confidence": result.confidence,
                        "intent": result.intent,
                        "urgency": result.urgency,
                        "opportunity_score": round(result.confidence * 100, 2),
                        "icp_fit_score": result.icp_fit_score if result.icp_fit_score > 0 else 50.0,
                        "final_score": round(result.confidence * 100, 2),
                        "score_band": _score_to_band(result.confidence),
                        "company_name": result.company_name,
                        "company_size": result.company_size,
                        "industry": result.industry,
                        "contact_name": result.contact_name,
                        "contact_title": result.contact_title,
                        "stage": "new",
                        "priority": "medium",
                        "outreach_draft": result.outreach_draft,
                        "analyzed_at": result.analyzed_at,
                    })
                    logger.debug("lead_upserted", lead_id=str(lead.id), is_opp=result.is_opportunity, score_band=lead.score_band, confidence=result.confidence)

                    # ── WRITE C: Quota tracking ───────────────────────────
                    if result.tokens_used > 0:
                        await quota_repo.increment(
                            model=result.model_used or settings.GEMINI_MODEL,
                            tokens=result.tokens_used,
                            requests=1,
                        )
                        logger.debug("quota_incremented", tokens=result.tokens_used, model=result.model_used)

                # ── BLOCK 6: Redis publish (after DB committed) ───────────
                payload = {
                    "lead_id": str(lead.id),
                    "source": source,
                    "is_opportunity": str(result.is_opportunity).lower(),
                    "intent": result.intent,
                    "score": str(lead.final_score),
                    "score_band": lead.score_band,
                    "company_name": result.company_name or "",
                    "analyzed_at": result.analyzed_at.isoformat(),
                }

                await redis_stream.publish(settings.STREAM_ANALYZED, payload)
                await redis_stream.ack(stream, group, event.event_id)

                # ── BLOCK 7: Final success log ───────────────────────────
                logger.info(
                    event="lead_persisted",
                    lead_id=str(lead.id),
                    source=source,
                    is_opportunity=result.is_opportunity,
                    confidence=result.confidence,
                    intent=result.intent,
                    score_band=lead.score_band,
                    tokens_used=result.tokens_used,
                    model=result.model_used,
                )

            except IntegrityError as exc:
                logger.warning("lead_already_exists", event_id=event.event_id, source=source, error=str(exc)[:200])
                _clear_retry(event.event_id)
                await redis_stream.ack(stream, group, event.event_id)

            except GeminiExtractionError as exc:
                retry_count = _record_retry(event.event_id)
                if retry_count >= _MAX_RETRIES:
                    logger.error(
                        "analyzer_permanent_dlq",
                        event_id=event.event_id,
                        source=source,
                        error=str(exc),
                        retries=retry_count,
                    )
                    await redis_stream.xadd("lead:failed", {
                        "event_id": event.event_id,
                        "source": source,
                        "url": url,
                        "reason": f"gemini_permanent_after_{retry_count}_retries",
                        "error": str(exc)[:500],
                        "ts": datetime.now(UTC).isoformat(),
                    })
                    _clear_retry(event.event_id)
                    await redis_stream.ack(stream, group, event.event_id)
                else:
                    logger.warning(
                        "analyzer_gemini_retry",
                        event_id=event.event_id,
                        source=source,
                        error=str(exc),
                        retry=retry_count,
                    )

            except SQLAlchemyError as exc:
                retry_count = _record_retry(event.event_id)
                if retry_count >= _MAX_RETRIES:
                    logger.error(
                        "analyzer_db_permanent_dlq",
                        event_id=event.event_id,
                        source=source,
                        error=str(exc)[:200],
                        retries=retry_count,
                    )
                    await redis_stream.xadd("lead:failed", {
                        "event_id": event.event_id,
                        "source": source,
                        "url": url,
                        "reason": f"db_transient_exhausted_{retry_count}",
                        "error": str(exc)[:500],
                        "ts": datetime.now(UTC).isoformat(),
                    })
                    _clear_retry(event.event_id)
                    await redis_stream.ack(stream, group, event.event_id)
                else:
                    logger.warning(
                        "analyzer_db_retry",
                        event_id=event.event_id,
                        source=source,
                        error=str(exc)[:200],
                        retry=retry_count,
                    )

            except Exception as exc:
                retry_count = _record_retry(event.event_id)
                if retry_count >= _MAX_RETRIES:
                    logger.error(
                        "analyzer_unknown_permanent_dlq",
                        event_id=event.event_id,
                        source=source,
                        error=str(exc)[:200],
                        error_type=type(exc).__name__,
                        retries=retry_count,
                    )
                    await redis_stream.xadd("lead:failed", {
                        "event_id": event.event_id,
                        "source": source,
                        "url": url,
                        "reason": f"unknown_exhausted_{retry_count}",
                        "error": str(exc)[:500],
                        "ts": datetime.now(UTC).isoformat(),
                    })
                    _clear_retry(event.event_id)
                    await redis_stream.ack(stream, group, event.event_id)
                else:
                    logger.error(
                        "analyzer_event_retry",
                        event_id=event.event_id,
                        source=source,
                        error=str(exc)[:200],
                        error_type=type(exc).__name__,
                        retry=retry_count,
                    )
                _prune_retry_counter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict[str, Any]:
    """Extract JSON from Gemini response, handling markdown code fences."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    return json.loads(cleaned)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)
