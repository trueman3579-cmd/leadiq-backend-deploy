"""
collectors/github.py — GitHub Issues/Discussions collector via REST API v3.
Env vars required: GITHUB_TOKEN (read-only scope sufficient)

Targets: issues/discussions with 'help wanted', 'bug', 'question', or 'tool' labels
in high-traffic repos relevant to your ICP.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from backend.collectors.base import BaseCollector, RawPost
from backend.shared.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
TARGET_REPOS: list[str] = [
    "vercel/next.js",
    "supabase/supabase",
    "raycast/extensions",
    "calcom/cal.com",
    "formbricks/formbricks",
]
LABELS = ["help wanted", "question", "bug", "discussion"]


class GithubCollector(BaseCollector):
    source = "github"

    def __init__(self, issues_per_repo: int = 20) -> None:
        self._limit = issues_per_repo

    async def collect(self) -> list[RawPost]:
        if not settings.GITHUB_TOKEN:
            logger.warning("GITHUB_TOKEN not set — skipping GithubCollector")
            return []

        headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        posts: list[RawPost] = []

        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            for repo in TARGET_REPOS:
                try:
                    resp = await client.get(
                        f"{GITHUB_API}/repos/{repo}/issues",
                        params={
                            "state": "open",
                            "sort": "created",
                            "direction": "desc",
                            "per_page": self._limit,
                            "since": since,
                        },
                    )
                    resp.raise_for_status()
                    for issue in resp.json():
                        if "pull_request" in issue:
                            continue  # skip PRs
                        labels = [lbl["name"] for lbl in issue.get("labels", [])]
                        posts.append(
                            RawPost(
                                source=self.source,
                                external_id=str(issue["id"]),
                                url=issue["html_url"],
                                title=issue["title"],
                                body=issue.get("body") or "",
                                author=issue.get("user", {}).get("login", ""),
                                score=issue.get("reactions", {}).get("+1", 0),
                                collected_at=datetime.fromisoformat(
                                    issue["created_at"].replace("Z", "+00:00")
                                ),
                                raw_meta={
                                    "repo": repo,
                                    "issue_number": issue["number"],
                                    "labels": labels,
                                    "comments": issue.get("comments", 0),
                                },
                            )
                        )
                except httpx.HTTPStatusError as exc:
                    logger.warning("GithubCollector HTTP error for %s: %d", repo, exc.response.status_code)
                except Exception as exc:
                    logger.warning("GithubCollector error for %s: %s", repo, exc)

        logger.info("GithubCollector fetched %d issues", len(posts))
        return posts
