"""
collectors/github_issues.py — GitHub Issues & Discussions scraper.
Targets: "help wanted", "hiring", "good first issue", "bug" in target repos.
"""
from __future__ import annotations

import logging

import httpx
from datetime import UTC, datetime
from backend.collectors.base import BaseCollector, RawPost
from backend.shared.config import settings

logger = logging.getLogger(__name__)

GITHUB_TOKEN = settings.GITHUB_TOKEN

TARGET_REPOS = [
    "facebook/react", "vercel/next.js", "microsoft/vscode",
    "kubernetes/kubernetes", "golang/go", "rust-lang/rust",
    "apache/kafka", "elastic/elasticsearch",
]

def _github_headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h
LABELS = ["help wanted", "good first issue", "hiring", "bug", "feature request"]

class GitHubIssuesCollector(BaseCollector):
    source = "github_issues"

    def __init__(self, per_repo: int = 30, repos: list[str] | None = None) -> None:
        self._per_repo = per_repo
        self._repos = repos or TARGET_REPOS

    async def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        async with httpx.AsyncClient(timeout=20.0, headers=_github_headers()) as client:
            for repo in self._repos:
                try:
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo}/issues",
                        params={
                            "state": "open",
                            "sort": "created",
                            "direction": "desc",
                            "per_page": self._per_repo,
                        },
                        headers={"Accept": "application/vnd.github+json"},
                    )
                    resp.raise_for_status()
                    for item in resp.json():
                        if "pull_request" in item:
                            continue
                        labels = [l["name"] for l in item.get("labels", [])]
                        posts.append(RawPost(
                            source=self.source,
                            external_id=str(item["id"]),
                            url=item["html_url"],
                            title=item["title"],
                            body=item.get("body") or "",
                            author=item.get("user", {}).get("login", "unknown"),
                            score=item.get("reactions", {}).get("+1", 0),
                            raw_meta={
                                "repo": repo,
                                "labels": labels,
                                "comments": item.get("comments", 0),
                                "created_at": item["created_at"],
                            },
                            collected_at=datetime.now(UTC),
                        ))
                except Exception as exc:
                    logger.warning("GitHubIssues collector error for %s: %s", repo, exc)
        logger.info("GitHubIssuesCollector fetched %d issues", len(posts))
        return posts
