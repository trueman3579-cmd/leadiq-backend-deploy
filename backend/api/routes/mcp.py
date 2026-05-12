"""
backend/api/routes/mcp.py — MCP Tools API Endpoint

Provides REST endpoint to list all MCP tools for introspection.
Mount in main.py:  app.include_router(router, prefix="/api/mcp")

Usage:
    GET /api/mcp/tools  → List all available MCP tools
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from slowapi.util import get_remote_address
from slowapi import Limiter

from backend.api.mcp_server import mcp

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


@router.get("/tools")
@limiter.limit("100/minute")
async def list_mcp_tools(request: Request) -> dict[str, list[dict[str, Any]]]:
    """
    List all MCP tools available via the MCP server.

    This endpoint provides an introspectable list of all MCP tools
    for debugging, documentation, or UI display.
    """
    tools = []
    for name, func in mcp._tools.items():
        tools.append({
            "name": name,
            "description": func.__doc__,
            "parameters": {
                "type": "object",
                "properties": {},
            },
        })
    return {"tools": tools}


@router.get("/resources")
async def list_mcp_resources() -> dict[str, list[dict[str, Any]]]:
    """
    List all MCP resources available via the MCP server.
    """
    resources = []
    for name, func in mcp._resources.items():
        resources.append({
            "name": name,
            "description": func.__doc__,
        })
    return {"resources": resources}


@router.get("/prompts")
async def list_mcp_prompts() -> dict[str, list[dict[str, Any]]]:
    """
    List all MCP prompts available via the MCP server.
    """
    prompts = []
    for name, func in mcp._prompts.items():
        prompts.append({
            "name": name,
            "description": func.__doc__,
        })
    return {"prompts": prompts}


@router.get("/health")
async def mcp_health() -> dict[str, str]:
    """
    Health check for MCP server.
    """
    return {"status": "ok", "server": "LeadIQ MCP"}
