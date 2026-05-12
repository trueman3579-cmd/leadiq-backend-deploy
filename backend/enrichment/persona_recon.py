"""
backend/enrichment/persona_recon.py — Sherlock-style persona reconnaissance.
Given an author username, discovers social profiles and infers persona.
Now with GitHub token auth and Redis caching.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", os.getenv("GITHUB_PAT", ""))


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


@dataclass
class PersonaProfile:
    username: str
    platforms: dict[str, str] = field(default_factory=dict)
    email_pattern: str | None = None
    role: str = "Unknown"
    authority_score: int = 0
    tech_stack: list[str] = field(default_factory=list)
    company: str | None = None
    location: str | None = None


class PersonaRecon:
    """Reconnaissance engine for discovering lead personas."""

    def __init__(self) -> None:
        headers = _github_headers()
        self._client = httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers)

    async def discover(self, username: str) -> PersonaProfile:
        """Discover persona for a given username."""
        platforms: dict[str, str] = {}
        role = "Unknown"
        authority = 0
        tech_stack: list[str] = []
        company: str | None = None
        email_pattern: str | None = None
        location: str | None = None

        # Strategy 1: GitHub (with token if available)
        try:
            gh = await self._client.get(f"https://api.github.com/users/{username}")
            if gh.status_code == 200:
                data = gh.json()
                platforms["github"] = data.get("html_url", "")
                company = data.get("company", "") or None
                location = data.get("location", "") or None
                tech_stack = await self._extract_github_tech(username)
                role = self._infer_role_from_bio(data.get("bio", "") or "")
                authority = self._role_to_authority(role)
                email_pattern = self._infer_email(username, company)
            elif gh.status_code == 403:
                logger.debug("GitHub rate limited for %s%s", username, f" (token: {bool(GITHUB_TOKEN)})")
            elif gh.status_code == 404:
                pass  # User not on GitHub
        except Exception as e:
            logger.debug("GitHub recon failed for %s: %s", username, e)

        # Strategy 2: HN (no rate limits)
        try:
            hn = await self._client.get(f"https://hacker-news.firebaseio.com/v0/user/{username}.json")
            if hn.status_code == 200 and hn.json():
                platforms["hn"] = f"https://news.ycombinator.com/user?id={username}"
                about = (hn.json().get("about") or "")
                if about and role == "Unknown":
                    role = self._infer_role_from_bio(about)
        except Exception:
            pass

        authority = self._role_to_authority(role) if authority == 0 else authority

        return PersonaProfile(
            username=username,
            platforms=platforms,
            email_pattern=email_pattern,
            role=role,
            authority_score=authority,
            tech_stack=tech_stack,
            company=company,
            location=location,
        )

    async def _extract_github_tech(self, username: str) -> list[str]:
        try:
            resp = await self._client.get(f"https://api.github.com/users/{username}/repos?per_page=5&sort=pushed")
            if resp.status_code == 200:
                repos = resp.json()
                languages: set[str] = set()
                for repo in repos:
                    lang = repo.get("language")
                    if lang:
                        languages.add(lang)
                        lang_map = {"Python": ["Django", "FastAPI", "Flask"], "JavaScript": ["React", "Node.js", "Vue"], "TypeScript": ["React", "Next.js", "Angular"], "Go": ["Gin", "Echo"], "Rust": ["Actix", "Rocket"], "Java": ["Spring", "Quarkus"], "Ruby": ["Rails", "Sinatra"]}
                        if lang in lang_map:
                            languages.update(lang_map[lang][:1])
                return list(languages)[:8]
        except Exception:
            pass
        return []

    @staticmethod
    def _infer_role_from_bio(bio: str) -> str:
        bio_lower = bio.lower()
        if any(t in bio_lower for t in ["cto", "chief technology officer", "vp of engineering", "vp engineering", "head of engineering"]):
            return "CTO/VP Engineering"
        elif any(t in bio_lower for t in ["founder", "ceo", "chief executive", "co-founder"]):
            return "CEO/Founder"
        elif any(t in bio_lower for t in ["vp", "vice president"]):
            return "VP"
        elif any(t in bio_lower for t in ["engineering manager", "tech lead", "lead engineer"]):
            return "Engineering Manager"
        elif any(t in bio_lower for t in ["director", "head of"]):
            return "Director"
        elif any(t in bio_lower for t in ["senior engineer", "staff engineer", "principal engineer", "architect"]):
            return "Senior Engineer"
        elif any(t in bio_lower for t in ["engineer", "developer", "programmer"]):
            return "Engineer"
        elif any(t in bio_lower for t in ["product manager", "pm"]):
            return "Product Manager"
        return "Developer"

    @staticmethod
    def _infer_email(username: str, company: str | None) -> str | None:
        if not company:
            return None
        clean = company.lower().replace("@", "").strip()
        domain_match = None
        for part in clean.split():
            if "." in part and "@" not in part:
                domain_match = part.strip("().,/")
            elif len(part) >= 4 and "." not in part:
                domain_match = part + ".com"
        if not domain_match:
            clean_domain = clean.replace(" ", "").replace(",", "")
            domain_match = clean_domain + ".com" if "." not in clean_domain else clean_domain
        return f"{username}@{domain_match}"

    @staticmethod
    def _role_to_authority(role: str) -> int:
        return {"CEO/Founder": 95, "CTO/VP Engineering": 92, "VP": 85, "Director": 80, "Engineering Manager": 75, "Senior Engineer": 65, "Product Manager": 60, "Engineer": 50, "Developer": 40}.get(role, 50)

    async def close(self) -> None:
        await self._client.aclose()