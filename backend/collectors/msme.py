"""DEPRECATED collector. Endpoint is no longer available."""
from __future__ import annotations
from backend.collectors.base import BaseCollector


class MSMECollector(BaseCollector):
    source = "msme"
    enabled = False

    async def collect(self) -> list:
        return []
