"""
backend/ml/qualitative_scorer.py — LLM-based Qualitative Lead Scorer.

Based on: asLLR (arXiv 2510.21713) — AUC 0.8127, 9.5% sales increase.

Uses Gemini to analyze unstructured lead context (company description,
job posting, signals) and return qualitative assessments including:
    - qualitative_score (0-100)
    - buying_signals
    - objection_risks
    - company_maturity
    - budget_indicators
    - recommended_approach
    - priority_reasoning
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from backend.llm.gemini_service import GeminiService
from backend.ml.scoring_model import LeadProtocol

logger = structlog.get_logger()


class LLMQualitativeScorer:
    """LLM-based qualitative lead analysis.

    Uses Gemini to evaluate unstructured lead context and produce
    structured qualitative scores and recommendations.

    Usage:
        scorer = LLMQualitativeScorer()
        analysis = await scorer.analyze(lead)
    """

    def __init__(self) -> None:
        self.llm = GeminiService()

    async def analyze(self, lead: LeadProtocol) -> dict[str, Any]:
        """Perform qualitative analysis of a lead.

        Args:
            lead: Lead to analyze.

        Returns:
            Dict with keys: qualitative_score, buying_signals,
            objection_risks, company_maturity, budget_indicators,
            recommended_approach, priority_reasoning.
        """
        prompt = self._build_prompt(lead)

        try:
            response = await self.llm.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
            )
        except Exception as exc:
            logger.error(
                "llm_qualitative_failed",
                lead_id=getattr(lead, "id", None),
                error=str(exc),
            )
            return self._fallback_result()

        result = self._parse_response(response)

        logger.info(
            "llm_qualitative_analysis",
            lead_id=getattr(lead, "id", None),
            score=result["qualitative_score"],
        )

        return result

    # ── Prompt Building ─────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(lead: LeadProtocol) -> str:
        """Build the analysis prompt with lead context."""
        raw_meta = getattr(lead, "raw_meta", {}) or {}
        engagement = getattr(lead, "engagement_metrics", {}) or {}

        return f"""Analyze this B2B lead and score its quality for outreach.

Company: {getattr(lead, 'company_name', None) or 'Unknown'}
Industry: {getattr(lead, 'industry', None) or 'Unknown'}
Source: {getattr(lead, 'source', None) or 'Unknown'}
Location: {getattr(lead, 'location', None) or 'Unknown'}
Job Title: {getattr(lead, 'job_title', None) or getattr(lead, 'contact_title', None) or 'N/A'}
Skills: {', '.join(getattr(lead, 'skills', None) or [])}
Experience Required: {getattr(lead, 'experience_required', None) or 'N/A'}
Salary Range: {getattr(lead, 'salary_range_min', None) or 'N/A'} - {getattr(lead, 'salary_range_max', None) or 'N/A'}
Company Size: {getattr(lead, 'company_size', None) or 'Unknown'}

Description: {getattr(lead, 'body', None) or 'N/A'}

Recent Signals:
- Government Registered: {'Yes' if getattr(lead, 'gst_number', None) or getattr(lead, 'udyam_number', None) else 'No'}
- DPIIT Recognized: {'Yes' if getattr(lead, 'source', None) == 'dpiit' else 'No'}
- Active Hiring: {'Yes' if int(raw_meta.get('job_count', 0)) > 0 else 'No'}
- Funding Stage: {raw_meta.get('funding_stage', 'Unknown')}
- Page Views: {engagement.get('page_views', 0)}
- Email Opens: {engagement.get('email_opens', 0)}

Return JSON with:
{{
    "qualitative_score": integer 0-100,
    "buying_signals": [list of observed buying signals],
    "objection_risks": [list of potential objections],
    "company_maturity": "early_growth" | "scaling" | "enterprise",
    "budget_indicators": "high" | "medium" | "low",
    "recommended_approach": "one-sentence outreach strategy",
    "priority_reasoning": "why this lead is high/medium/low priority"
}}
"""

    # ── Response Parsing ────────────────────────────────────────────────

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        """Parse LLM response into a structured result dict.

        Extracts the first JSON object from the response text.
        Falls back to sensible defaults if parsing fails.
        """
        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())

                return {
                    "qualitative_score": result.get("qualitative_score", 50),
                    "buying_signals": result.get("buying_signals", []),
                    "objection_risks": result.get("objection_risks", []),
                    "company_maturity": result.get("company_maturity", "unknown"),
                    "budget_indicators": result.get("budget_indicators", "medium"),
                    "recommended_approach": result.get("recommended_approach", ""),
                    "priority_reasoning": result.get("priority_reasoning", ""),
                }
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            logger.error("llm_response_parse_failed", error=str(exc))

        return self._fallback_result()

    @staticmethod
    def _fallback_result() -> dict[str, Any]:
        """Return safe defaults when parsing or API call fails."""
        return {
            "qualitative_score": 50,
            "buying_signals": [],
            "objection_risks": [],
            "company_maturity": "unknown",
            "budget_indicators": "medium",
            "recommended_approach": "",
            "priority_reasoning": "",
        }
