"""
backend/services — domain-level services (stateless, pure logic).

Services:
    - confidence: Lead confidence scoring
    - dedup_service: 3-tier deduplication
    - feature_flags: Actor feature flags (enable/disable at runtime)
    - icp_service: ICP parsing and semantic matching
    - intent_monitor: Intent signal refresh with temporal decay
    - personalization: Query generation and personalization
    - velocity: Velocity scoring
    - waterfall_enrichment: Multi-tier enrichment pipeline
"""

from . import feature_flags

__all__ = ["feature_flags"]
