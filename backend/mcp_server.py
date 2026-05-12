"""
backend/mcp_server.py — LeadIQ MCP Server
Exposes lead intelligence tools for AI agents (Claude, Cursor, VS Code).
Inspired by Apify MCP Server architecture.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.pipeline_v3 import run_full_pipeline
from backend.engine.scorer import MultiDimensionalScorer
from backend.intelligence.trends import TrendAnalyzer
from backend.intelligence.signal_fusion import SignalFusionEngine
from backend.intelligence.anomaly_detector import AnomalyDetector

logger = logging.getLogger(__name__)

scorer = MultiDimensionalScorer()
trends = TrendAnalyzer()
fusion = SignalFusionEngine()
anomaly = AnomalyDetector()

MCP_TOOLS = {
    "find_leads": {
        "description": "Run the full LeadIQ pipeline and return scored leads",
        "parameters": {"keywords": "Optional keyword filter"},
        "handler": "handle_find_leads",
    },
    "enrich_profile": {
        "description": "Enrich a lead with persona, email, tech stack",
        "parameters": {"username": "GitHub/HN username"},
        "handler": "handle_enrich_profile",
    },
    "score_signal": {
        "description": "Score a single lead signal for intent",
        "parameters": {"text": "Signal text", "sources": "Comma-separated sources"},
        "handler": "handle_score_signal",
    },
    "get_trending_topics": {
        "description": "Get current market trends",
        "parameters": {},
        "handler": "handle_get_trending_topics",
    },
    "export_leads_csv": {
        "description": "Export all leads to CSV format",
        "parameters": {"min_score": "Minimum score to include"},
        "handler": "handle_export_leads",
    },
    "detect_anomalies": {
        "description": "Detect signal anomalies and spikes",
        "parameters": {},
        "handler": "handle_detect_anomalies",
    },
}


async def handle_find_leads(**kwargs) -> dict[str, Any]:
    result = await run_full_pipeline()
    leads = [
        {
            "score": lead["score"].overall,
            "confidence": lead["score"].confidence,
            "title": lead["post"].title[:100],
            "source": lead["post"].source,
            "url": lead["post"].url,
            "dimensions": {k: v for k, v in lead["score"].dimensions.items() if v > 30},
        }
        for lead in result["leads"]
    ]
    return {"leads": leads[:50], "stats": result["stats"]}


async def handle_enrich_profile(username: str, **kwargs) -> dict:
    from backend.enrichment.persona_recon import PersonaRecon
    recon = PersonaRecon()
    profile = await recon.discover(username)
    return {
        "username": profile.username,
        "platforms": profile.platforms,
        "email": profile.email_pattern,
        "role": profile.role,
        "authority": profile.authority_score,
        "tech_stack": profile.tech_stack,
    }


async def handle_score_signal(text: str, sources: str = "unknown", **kwargs) -> dict:
    src_list = sources.split(",") if sources else ["unknown"]
    result = scorer.score(text, sources=src_list, recency_days=0)
    return {
        "overall": result.overall,
        "confidence": result.confidence,
        "dimensions": {k: v for k, v in result.dimensions.items() if v > 30},
        "reasoning": result.reasoning[:5],
    }


async def handle_get_trending_topics(**kwargs) -> dict:
    trend_data = trends.extract_topics([])
    return {
        "trends": list(trend_data)[:10],
        "count": len(trend_data),
    }


async def handle_export_leads(min_score: str = "0", **kwargs) -> dict:
    threshold = int(min_score)
    result = await run_full_pipeline()
    leads = [
        {
            "score": l["score"].overall,
            "confidence": l["score"].confidence,
            "title": l["post"].title,
            "source": l["post"].source,
            "url": l["post"].url,
            "author": l["post"].author,
        }
        for l in result["leads"]
        if l["score"].overall >= threshold
    ]
    csv_header = "score,confidence,title,source,url,author\n"
    csv_body = "\n".join(
        f'{lead["score"]},{lead["confidence"]},"{lead["title"].replace(chr(34),chr(92)+chr(34))}",{lead["source"]},{lead["url"]},{lead["author"]}'
        for lead in leads
    )
    return {"csv": csv_header + csv_body, "count": len(leads)}


async def handle_detect_anomalies(**kwargs) -> dict:
    result = await run_full_pipeline()
    return {
        "anomalies": result.get("anomalies", [])[:20],
        "fusions": result.get("fusions", [])[:10],
    }


HANDLER_MAP = {
    "handle_find_leads": handle_find_leads,
    "handle_enrich_profile": handle_enrich_profile,
    "handle_score_signal": handle_score_signal,
    "handle_get_trending_topics": handle_get_trending_topics,
    "handle_export_leads": handle_export_leads,
    "handle_detect_anomalies": handle_detect_anomalies,
}


async def invoke_tool(tool_name: str, **kwargs) -> dict[str, Any]:
    """Invoke an MCP tool by name."""
    tool = MCP_TOOLS.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}", "available": list(MCP_TOOLS.keys())}

    handler_name = tool["handler"]
    handler = HANDLER_MAP.get(handler_name)
    if not handler:
        return {"error": f"Handler not found: {handler_name}"}

    try:
        return await handler(**kwargs)
    except Exception as e:
        logger.error("MCP tool %s failed: %s", tool_name, e)
        return {"error": str(e), "tool": tool_name}