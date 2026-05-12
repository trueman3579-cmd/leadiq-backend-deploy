"""DEPRECATED collector. Endpoint is no longer available."""
from __future__ import annotations
from backend.collectors.base import BaseCollector


class MCA21Collector(BaseCollector):
    source = "mca21"
    enabled = False

    async def collect(self) -> list:
        return []
