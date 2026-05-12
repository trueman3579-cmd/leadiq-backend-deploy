"""DEPRECATED collector. Endpoint is no longer available."""
from __future__ import annotations
from backend.collectors.base import BaseCollector


class DPIITv2Collector(BaseCollector):
    source = "dpiit_v2"
    enabled = False

    async def collect(self) -> list:
        return []
