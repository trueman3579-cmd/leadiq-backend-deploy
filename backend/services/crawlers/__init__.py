"""
backend/services/crawlers/ — Pluggable crawler layer for LeadIQ signals.
Each crawler collects data from a primary source and persists to the database.
"""

from backend.services.crawlers.base import BaseCrawler, CrawlResult

__all__ = ["BaseCrawler", "CrawlResult"]