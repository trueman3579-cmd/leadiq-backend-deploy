"""
scraping_utils.py — Core scraping utilities for LeadIQ
Anti-detection, stealth configuration, and utility tools.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()


@dataclass
class StealthConfig:
    """Configuration for stealth scraping sessions."""

    browser: str = "playwright"
    headless: bool = True
    user_agent_rotation: bool = True
    proxy_type: str = "residential"
    proxy_rotation_interval: int = 20
    delay_min: float = 2.0
    delay_max: float = 5.0
    tls_bypass: str = "curl_cffi"
    fingerprint_spoofing: bool = True
    mouse_movement: bool = True
    scroll_simulation: bool = True


class UserAgentRotator:
    """Rotate user agents from real browser signatures."""

    USER_AGENTS: list[str] = [
        # Chrome 120 on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Chrome 119 on Windows (Edge)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        # Chrome 120 on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Firefox 120 on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) "
        "Gecko/20100101 Firefox/120.0",
        # Firefox 120 on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) "
        "Gecko/20100101 Firefox/120.0",
        # Safari 17.1 on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        # Safari 17.2 on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    def get_random(self) -> str:
        return random.choice(self.USER_AGENTS)

    def get_for_browser(self, browser: str) -> str:
        browsers = {
            "chrome": [
                ua for ua in self.USER_AGENTS
                if "Chrome" in ua and "Edg" not in ua
            ],
            "edge": [
                ua for ua in self.USER_AGENTS if "Edg" in ua
            ],
            "firefox": [
                ua for ua in self.USER_AGENTS if "Firefox" in ua
            ],
            "safari": [
                ua for ua in self.USER_AGENTS
                if "Safari" in ua and "Chrome" not in ua
            ],
        }
        pool = browsers.get(browser, self.USER_AGENTS)
        return random.choice(pool)


class TLSFingerprintManager:
    """Manage TLS fingerprint to avoid detection."""

    def __init__(self, method: str = "curl_cffi") -> None:
        self.method = method

    def create_session(self):
        """Create a session with browser-like TLS fingerprint."""
        if self.method == "curl_cffi":
            from curl_cffi import requests  # type: ignore[import-untyped]
            return requests.Session(impersonate="chrome120")
        if self.method == "tls_client":
            from tls_client import Session  # type: ignore[import-untyped]
            return Session(client_identifier="chrome_120")
        import httpx
        return httpx.AsyncClient()

    def create_context(self):
        """Alias for create_session — backward compat."""
        return self.create_session()


class StealthHeaders:
    """Consolidated stealth headers generator for HTTP collectors.

    Replaces the copy-pasted _stealth_headers() in 16 job collectors.
    Generates browser-like headers with dynamic Accept-Language and referer.
    """

    DEFAULT_REFERERS = [
        "https://www.google.com/",
        "https://www.bing.com/",
        "https://search.yahoo.com/",
        "",
    ]

    @classmethod
    def generate(cls, referer: str | None = None, ua: str | None = None) -> dict[str, str]:
        ua_rotator = UserAgentRotator()
        return {
            "User-Agent": ua or ua_rotator.get_random(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": random.choice([
                "en-US,en;q=0.9",
                "en-GB,en;q=0.8",
                "en-IN,en;q=0.9,hi;q=0.8",
                "en-CA,en;q=0.8",
            ]),
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": referer or random.choice(cls.DEFAULT_REFERERS),
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none" if not referer else "cross-site",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    @classmethod
    def mobile(cls, referer: str | None = None) -> dict[str, str]:
        ua_rotator = UserAgentRotator()
        return {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": referer or "https://www.google.com/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none" if not referer else "cross-site",
        }

    @classmethod
    def api(cls, token: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.google.com/",
            "Origin": "https://www.google.com",
            "Connection": "keep-alive",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers


class BaseHttpCollector:
    """Base for HTTP+BS4 job collectors.

    and automatically handles stealth headers, retry, and error classification.
    Subclasses define search_urls() and _parse() only.
    """

    source: str = ""
    search_url_template: str = ""

    def __init__(self, adapter=None):
        self.adapter = adapter  # Optional httpx client, or None for default

    def search_urls(self, keyword: str, location: str | None = None) -> list[str]:
        raise NotImplementedError

    def _parse(self, html: str | bytes) -> list[dict]:
        raise NotImplementedError

    async def collect(self) -> list:
        from backend.collectors.base import RawPost
        from datetime import datetime, UTC
        import structlog
        logger = structlog.get_logger(__name__)

        all_posts = []
        for url in self.search_urls("", None):
            result = await self.adapter.fetch(url)
            if not result.is_success():
                logger.warning("fetch_failed", source=self.source, url=url, status=result.status, error=result.error)
                continue
            items = self._parse(result.data.get("text", ""))
            for item in items:
                all_posts.append(RawPost(
                    source=self.source,
                    external_id=str(hash(str(item))),
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    body=item.get("description", ""),
                    author=item.get("company", ""),
                    score=1,
                    raw_meta=item,
                    collected_at=datetime.now(UTC),
                ))
        return all_posts
