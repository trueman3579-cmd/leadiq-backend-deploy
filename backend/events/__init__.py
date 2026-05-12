"""
backend/events — Domain event emitter and feature flags.

Events:
    - lead_created: New lead detected
    - lead_enriched: Lead data enriched
    - lead_scored: Lead scored
    - signal_detected: Intent signal detected
    - lead_ranked: Lead ranked for outreach

Feature Flags:
    - Control actor enablement (tracxn, dpiit, mca21, etc.)
"""

from .emitter import emit, STREAMS as EVENT_STREAMS

__all__ = ["emit", "EVENT_STREAMS"]
