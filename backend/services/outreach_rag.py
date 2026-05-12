"""
outreach_rag.py — Generate personalized outreach using RAG context.

Builds LLM prompt with retrieved company facts and generates
personalized cold emails. Multi-LLM router integration.

Research: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
(Lewis et al., NeurIPS 2020) — grounding LLM in retrieved facts.
"""

from __future__ import annotations

import json
import logging
from typing import List

from backend.services.llm_router import get_llm_router
from backend.services.rag_retriever import RAGRetriever

logger = logging.getLogger(__name__)


OUTREACH_PROMPT_TEMPLATE = """You are a world-class B2B sales outreach expert.
Your goal: write a hyper-personalized cold email that feels like you've deeply researched the prospect.

## STRICT RULES:
1. Use ONLY the verified facts below — never hallucinate
2. Cite specific details (funding amounts, dates, product names)
3. Mention how your solution solves THEIR specific problem
4. Keep under 150 words
5. Professional but warm tone
6. Single clear call-to-action

## VERIFIED FACTS ABOUT {company_name}:
{rag_context}

## YOUR PRODUCT/SERVICE:
{product_description}

## USER'S VALUE PROPOSITION:
{value_proposition}

## OUTPUT FORMAT:
Return valid JSON:
{{
  "subject": "compelling subject line (under 60 chars)",
  "body": "personalized email body (under 150 words)",
  "personalization_score": 0-10,
  "sources_used": ["source_type: specific_fact"],
  "confidence": "high|medium|low"
}}
"""


class OutreachRAG:
    """
    Generate personalized outreach using RAG-retrieved company facts.

    Flow:
        1. Retrieve relevant context from pgvector
        2. Build structured prompt
        3. Call LLM via multi-LLM router
        4. Validate and format output
    """

    def __init__(self):
        self.retriever = RAGRetriever(min_trust_score=5.0, top_k=5)
        self.llm = get_llm_router()

    async def generate_outreach(
        self,
        company_id: str,
        company_name: str,
        product_description: str,
        value_proposition: str,
        user_query: str | None = None,
    ) -> dict:
        """
        Generate personalized outreach email.

        Args:
            company_id: Target company ID in pgvector
            company_name: Human-readable company name
            product_description: What you sell
            value_proposition: Why they should care
            user_query: Optional specific angle (e.g., "mention their Series B")

        Returns:
            {"subject": str, "body": str, "sources": [...], "confidence": str}
        """
        # Step 1: Retrieve RAG context
        query = user_query or f"{company_name} funding product hiring growth"
        rag_context = await self.retriever.get_context_for_prompt(
            company_id=company_id,
            query=query,
            max_chars=2000,
        )

        # Step 2: Build prompt
        prompt = OUTREACH_PROMPT_TEMPLATE.format(
            company_name=company_name,
            rag_context=rag_context,
            product_description=product_description,
            value_proposition=value_proposition,
        )

        # Step 3: Call LLM (via multi-LLM router) with structured JSON output
        llm_response = await self.llm.generate(
            prompt=prompt,
            task_type="generation",
            model_preference="nvidia:fast",
            temperature=0.7,
            max_tokens=500,
            json_mode=True,
        )

        # Step 4: Parse and validate
        try:
            result = json.loads(llm_response.text)
        except json.JSONDecodeError:
            result = self._parse_fallback(llm_response.text if llm_response.success else "")

        # Step 5: Add metadata
        result["metadata"] = {
            "company_id": company_id,
            "model_used": llm_response.model,
            "latency_ms": llm_response.latency_ms,
            "cost_usd": llm_response.cost_usd,
            "rag_sources": len(rag_context.split("[Source")) - 1,
        }

        logger.info(
            f"Generated outreach for {company_name} "
            f"(confidence={result.get('confidence', 'unknown')}, "
            f"model={result['metadata']['model_used']})"
        )

        return result

    async def generate_outreach_batch(
        self,
        targets: List[dict],
        product_description: str,
        value_proposition: str,
    ) -> List[dict]:
        """
        Generate outreach for multiple companies.

        Args:
            targets: List of {"company_id": str, "company_name": str}

        Returns:
            List of outreach results
        """
        results = []
        for target in targets:
            result = await self.generate_outreach(
                company_id=target["company_id"],
                company_name=target["company_name"],
                product_description=product_description,
                value_proposition=value_proposition,
            )
            results.append(result)
        return results

    def _parse_fallback(self, text: str) -> dict:
        """Parse non-JSON LLM output."""
        lines = text.strip().split("\n")
        subject = ""
        body_lines = []

        for line in lines:
            if "subject:" in line.lower() or "subject line:" in line.lower():
                subject = line.split(":", 1)[1].strip().strip('"')
            elif line.strip() and not line.lower().startswith("json"):
                body_lines.append(line)

        return {
            "subject": subject or "Partnership opportunity",
            "body": "\n".join(body_lines).strip() or text[:500],
            "personalization_score": 5,
            "sources_used": [],
            "confidence": "medium",
        }
