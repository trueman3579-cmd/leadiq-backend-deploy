"""
backend/services/pipeline_orchestrator.py — Pipeline Orchestrator.

Central nervous system that connects all pipeline stages into a cohesive data flow.

Stages:
  1. Collection  — trigger source-specific collection (jobs, government, social)
  2. Enrichment  — run waterfall enrichment (Hunter.io -> Clearbit -> Gemini)
  3. Dedup       — content hash + vector similarity dedup
  4. Scoring     — composite scoring (opportunity, ICP fit, confidence, intent)
  5. Ranking     — classify into band (hot/warm/cool/cold) and route

Each stage emits to the appropriate Redis stream for downstream consumers.
Handles errors with configurable retry logic.
"""
from __future__ import annotations

import structlog
import uuid
from datetime import datetime, UTC
from typing import Any

from backend.events.emitter import emit
from backend.shared.config import settings
from backend.shared.stream import redis_stream, RedisStreamClient

logger = structlog.get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the full lead pipeline from collection through routing.

    Usage:
        orchestrator = PipelineOrchestrator()
        result = await orchestrator.run_collection("naukri", {"keywords": ["python"]})
    """

    # ── Stream Names ──────────────────────────────────────────────────────────────

    STREAM_COLLECTED: str = settings.STREAM_COLLECTED  # lead:collected
    STREAM_JOBS: str = "lead:jobs_collected"
    STREAM_GOVT: str = "lead:govt_collected"
    STREAM_ENRICHED: str = "lead:enriched"
    STREAM_SCORED: str = settings.STREAM_SCORED  # lead:scored
    STREAM_RANKED: str = settings.STREAM_RANKED  # lead:ranked
    STREAM_ROUTED: str = "lead:routed"

    MAX_RETRIES: int = 3
    RETRY_DELAY_SECONDS: int = 5

    def __init__(self) -> None:
        self._stream: RedisStreamClient = redis_stream

    # ── Stage 1: Collection ───────────────────────────────────────────────────────

    async def run_collection(
        self,
        source: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run collection for a source and emit results to the appropriate stream.

        Args:
            source: Source identifier (naukri, internshala, dpiit, mca21, etc.)
            params: Source-specific parameters (keywords, locations, max_results, etc.)

        Returns:
            Dict with collection_id, source, status, stream_event_id
        """
        params = params or {}
        collection_id = str(uuid.uuid4())

        # Determine which stream to publish to based on source type
        if source in ("naukri", "internshala"):
            stream = self.STREAM_JOBS
        elif source in ("dpiit", "mca21", "gem", "msme"):
            stream = self.STREAM_GOVT
        else:
            stream = self.STREAM_COLLECTED

        payload: dict[str, Any] = {
            "collection_id": collection_id,
            "source": source,
            "params": params,
            "status": "collected",
            "collected_at": datetime.now(UTC).isoformat(),
        }

        last_error: str | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                event_id = await self._stream.publish(stream, payload)

                await emit("signal_detected", {
                    "source": source,
                    "collection_id": collection_id,
                    "stream": stream,
                    "stream_event_id": event_id,
                })

                logger.info(
                    "pipeline_collection_complete",
                    source=source,
                    collection_id=collection_id,
                    stream=stream,
                    attempt=attempt,
                )

                return {
                    "collection_id": collection_id,
                    "source": source,
                    "status": "published",
                    "stream": stream,
                    "stream_event_id": event_id,
                }
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "pipeline_collection_retry",
                    source=source,
                    collection_id=collection_id,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < self.MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)

        logger.error(
            "pipeline_collection_failed",
            source=source,
            collection_id=collection_id,
            error=last_error,
        )
        return {
            "collection_id": collection_id,
            "source": source,
            "status": "failed",
            "error": last_error,
        }

    # ── Stage 2: Enrichment ────────────────────────────────────────────────────────

    async def run_enrichment(self, lead_id: str) -> dict[str, Any]:
        """Enrich a single lead through the waterfall enrichment pipeline.

        Steps:
            1. Load lead data from database
            2. Run Hunter.io email enrichment
            3. Run Clearbit company enrichment
            4. Run Gemini fallback for missing fields
            5. Publish enriched data to lead:enriched stream

        Args:
            lead_id: UUID of the lead to enrich

        Returns:
            Dict with status and enrichment metadata
        """
        try:
            from backend.services.waterfall_enrichment import enrich_lead
            from backend.shared.repository import LeadRepo
            from backend.shared.db import get_db_session

            async with get_db_session() as session:
                repo = LeadRepo(session)
                lead = await repo.get(lead_id)

                if not lead:
                    logger.error("enrichment_lead_not_found", lead_id=lead_id)
                    return {"status": "not_found", "lead_id": lead_id}

                # Convert lead to dict for enrichment
                lead_dict = {
                    "company_name": lead.company_name,
                    "industry": lead.industry,
                    "url": getattr(lead, "url", None),
                    "body": getattr(lead, "body", None),
                    "source": getattr(lead, "source", "unknown"),
                    "company_size": lead.company_size,
                    "location": getattr(lead, "location", None),
                    "email": getattr(lead, "email", None),
                }

                # Run waterfall enrichment
                enriched = await enrich_lead(lead_dict, session)

                # Publish enriched data to stream
                enriched["lead_id"] = lead_id
                event_id = await self._stream.publish(self.STREAM_ENRICHED, enriched)

                await emit("lead_enriched", {
                    "id": lead_id,
                    "company_name": enriched.get("company_name"),
                    "enrichment_methods": enriched.get("enrichment_methods", []),
                    "enrichment_level": enriched.get("enrichment_level", 0),
                })

                logger.info(
                    "pipeline_enrichment_complete",
                    lead_id=lead_id,
                    methods=enriched.get("enrichment_methods", []),
                )

                return {
                    "status": "enriched",
                    "lead_id": lead_id,
                    "stream_event_id": event_id,
                    "enrichment_methods": enriched.get("enrichment_methods", []),
                    "enrichment_level": enriched.get("enrichment_level", 0),
                }

        except Exception as exc:
            logger.error("pipeline_enrichment_failed", lead_id=lead_id, error=str(exc))
            return {"status": "failed", "lead_id": lead_id, "error": str(exc)}

    # ── Stage 3: Scoring ───────────────────────────────────────────────────────────

    async def run_scoring(self, lead_id: str) -> dict[str, Any]:
        """Score a single lead through the composite scorer.

        Args:
            lead_id: UUID of the lead to score

        Returns:
            Dict with score, band, and component breakdown
        """
        try:
            from backend.shared.repository import LeadRepo
            from backend.shared.db import get_db_session

            async with get_db_session() as session:
                repo = LeadRepo(session)
                lead = await repo.get(lead_id)

                if not lead:
                    logger.error("scoring_lead_not_found", lead_id=lead_id)
                    return {"status": "not_found", "lead_id": lead_id}

                # Compute composite score
                from backend.services.confidence import compute_confidence

                opportunity_score = float(getattr(lead, "opportunity_score", 0.0) or 0.0)
                icp_fit = float(getattr(lead, "icp_fit_score", 0.0) or 0.0)
                confidence = float(getattr(lead, "confidence", 0.0) or 0.0)

                # Composite = opportunity (40%) + ICP fit (30%) + confidence (20%) + intent (10%)
                intent_map = {"buy": 90.0, "evaluate": 70.0, "pain": 60.0, "compare": 50.0}
                intent_raw = getattr(lead, "intent", None) or "other"
                intent_score = intent_map.get(intent_raw, 20.0)

                final_score = round(
                    (opportunity_score * 0.40)
                    + (icp_fit * 0.30)
                    + (confidence * 100.0 * 0.20)
                    + (intent_score * 0.10),
                    2,
                )

                # Determine band
                if final_score >= 80:
                    band = "hot"
                elif final_score >= 60:
                    band = "warm"
                elif final_score >= 40:
                    band = "cool"
                else:
                    band = "cold"

                # Persist score
                await repo.update_fields(lead_id, {
                    "final_score": final_score,
                    "score_band": band,
                    "scored_at": datetime.now(UTC),
                })

                # Publish to scored stream
                payload = {
                    "lead_id": lead_id,
                    "final_score": final_score,
                    "score_band": band,
                    "component_scores": {
                        "opportunity_score": round(opportunity_score * 0.40, 2),
                        "icp_fit_score": round(icp_fit * 0.30, 2),
                        "confidence": round(confidence * 100.0 * 0.20, 2),
                        "intent_signals": round(intent_score * 0.10, 2),
                    },
                    "scored_at": datetime.now(UTC).isoformat(),
                }
                await self._stream.publish(self.STREAM_SCORED, payload)

                await emit("lead_scored", {
                    "id": lead_id,
                    "final_score": final_score,
                    "score_band": band,
                })

                logger.info("pipeline_scoring_complete", lead_id=lead_id, score=final_score, band=band)

                return {
                    "status": "scored",
                    "lead_id": lead_id,
                    "final_score": final_score,
                    "score_band": band,
                    "components": payload["component_scores"],
                }

        except Exception as exc:
            logger.error("pipeline_scoring_failed", lead_id=lead_id, error=str(exc))
            return {"status": "failed", "lead_id": lead_id, "error": str(exc)}

    # ── Stage 4: Batch Scoring ──────────────────────────────────────────────────────

    async def run_batch_scoring(
        self,
        lead_ids: list[str],
    ) -> dict[str, Any]:
        """Score multiple leads in batch.

        Args:
            lead_ids: List of lead UUIDs to score

        Returns:
            Dict with summary (processed, failed) and per-lead results
        """
        results: list[dict[str, Any]] = []
        processed = 0
        failed = 0

        for lead_id in lead_ids:
            try:
                result = await self.run_scoring(lead_id)
                if result.get("status") == "scored":
                    processed += 1
                else:
                    failed += 1
                results.append(result)
            except Exception as exc:
                failed += 1
                results.append({"status": "failed", "lead_id": lead_id, "error": str(exc)})

        logger.info(
            "pipeline_batch_scoring_complete",
            total=len(lead_ids),
            processed=processed,
            failed=failed,
        )

        return {
            "status": "completed",
            "total": len(lead_ids),
            "processed": processed,
            "failed": failed,
            "results": results,
        }

    # ── Stage 5: Full Pipeline Run ──────────────────────────────────────────────────

    async def run_full_pipeline(self, lead_id: str) -> dict[str, Any]:
        """Run the full pipeline for a single lead: collect -> enrich -> score -> rank.

        This is a coordinated run where each stage feeds into the next.
        The lead must already exist in the database.

        Args:
            lead_id: UUID of the lead to process

        Returns:
            Dict with status of each pipeline stage
        """
        pipeline_result: dict[str, Any] = {
            "lead_id": lead_id,
            "stages": {},
            "status": "running",
        }

        # Stage 1: Enrichment
        logger.info("pipeline_full_stage_enrichment", lead_id=lead_id)
        enrich_result = await self.run_enrichment(lead_id)
        pipeline_result["stages"]["enrichment"] = enrich_result

        if enrich_result.get("status") == "failed":
            pipeline_result["status"] = "failed_at_enrichment"
            return pipeline_result

        # Stage 2: Scoring
        logger.info("pipeline_full_stage_scoring", lead_id=lead_id)
        score_result = await self.run_scoring(lead_id)
        pipeline_result["stages"]["scoring"] = score_result

        if score_result.get("status") == "failed":
            pipeline_result["status"] = "failed_at_scoring"
            return pipeline_result

        # Stage 3: Ranking and routing
        logger.info("pipeline_full_stage_routing", lead_id=lead_id)
        route_result = await self._run_routing(
            lead_id=lead_id,
            score_band=score_result.get("score_band", "cold"),
            final_score=score_result.get("final_score", 0.0),
        )
        pipeline_result["stages"]["routing"] = route_result

        pipeline_result["status"] = "completed"
        logger.info("pipeline_full_complete", lead_id=lead_id, result=pipeline_result["status"])

        return pipeline_result

    # ── Stage 5 Internal: Routing ───────────────────────────────────────────────────

    async def _run_routing(
        self,
        lead_id: str,
        score_band: str,
        final_score: float,
    ) -> dict[str, Any]:
        """Route a scored lead to the appropriate action.

        Routing rules:
            - hot:    Immediate outreach (email + LinkedIn)
            - warm:   Nurture sequence (automated email sequence)
            - cool:   Long-term nurture (monthly check-in)
            - cold:   Drip campaign (quarterly newsletter)

        Args:
            lead_id: UUID of the lead
            score_band: Lead band classification
            final_score: Composite score value

        Returns:
            Dict with routing decision
        """
        routing_rules: dict[str, str] = {
            "hot": "immediate_outreach",
            "warm": "nurture_sequence",
            "cool": "long_term_nurture",
            "cold": "drip_campaign",
        }

        action = routing_rules.get(score_band, "drip_campaign")

        payload: dict[str, Any] = {
            "lead_id": lead_id,
            "final_score": final_score,
            "score_band": score_band,
            "action": action,
            "priority": "high" if score_band in ("hot", "warm") else "low",
            "routed_at": datetime.now(UTC).isoformat(),
        }

        event_id = await self._stream.publish(self.STREAM_ROUTED, payload)

        await emit("lead_ranked", {
            "id": lead_id,
            "final_score": final_score,
            "score_band": score_band,
            "action": action,
        })

        logger.info("pipeline_routing_complete", lead_id=lead_id, action=action, band=score_band)

        return {
            "status": "routed",
            "lead_id": lead_id,
            "action": action,
            "priority": payload["priority"],
            "stream_event_id": event_id,
        }
