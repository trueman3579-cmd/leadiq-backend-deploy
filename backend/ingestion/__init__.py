"""
ingestion — LeadIQ data ingestion orchestration package.

This package provides unified ingestion orchestration for collecting leads
from multiple sources (collectors), running deduplication, and persisting
qualified leads to the database.

Ingestion Flow:
  Collectors → Redis Stream → Analyzer → Scorer → Persist → Database

Usage:
    from backend.ingestion.orchestrator import IngestionOrchestrator

    orchestrator = IngestionOrchestrator()
    result = await orchestrator.run_all()

Architecture:
    - orchestrator.py: Main orchestration logic
    - collectors.py: Collector factory and configuration
    - config.py: Ingestion-specific settings
    - metrics.py: Ingestion metrics tracking
"""

from backend.ingestion.orchestrator import IngestionOrchestrator
from backend.ingestion.collectors import get_collectors
from backend.ingestion.metrics import IngestionMetrics

__all__ = [
    "IngestionOrchestrator",
    "get_collectors",
    "IngestionMetrics",
]
