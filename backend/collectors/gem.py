"""DEPRECATED collector. Endpoint is no longer available."""
from __future__ import annotations
from backend.collectors.base import BaseCollector


class GeMCollector(BaseCollector):
    source = "gem"
    enabled = False

    async def collect(self) -> list:
        return []
