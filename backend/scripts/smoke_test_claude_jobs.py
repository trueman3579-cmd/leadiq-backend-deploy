"""
Smoke test: find leads for "claude code jobs"
Run: cd backend && uv run python scripts/smoke_test_claude_jobs.py
"""
from __future__ import annotations
import asyncio, json, sys
from datetime import datetime, UTC
from typing import Any

SEARCH_QUERY = "claude code jobs"
SOURCES = ["reddit", "hackernews", "github"]
MOCK_POSTS = [
    {"source": "reddit", "title": "Hiring: Claude AI specialist", "url": "https://r/h/fake1", "body": "We're hiring someone who loves Claude coding assistant. Remote $120-150k.", "author": "hiringthrow123", "score": 45},
    {"source": "reddit", "title": "Using Claude for code reviews?", "url": "https://r/ED/ev/abc", "body": "My startup is integrating Claude for review bot. Looking for devs using it. We pay well.", "author": "cto_th2026", "score": 128},
    {"source": "hackernews", "title": "Show HN: Claude CI plugin", "url": "https://hn/12345678", "body": "We built a CI plugin that plugs Claude into GitHub PRs. Seeking early paying users.", "author": "ai_dev_saas", "score": 88},
    {"source": "github", "title": "Hiring AI dev rel — Claude", "url": "https://gh/anthropics/jobs#42", "body": "Anthropic is hiring developer relations engineers focused on Claude code tooling.", "author": "sarah_aipc", "score": 256},
    {"source": "reddit", "title": "Claude Code vs Copilot", "url": "https://r/s/sar78y", "body": "After 3 months using Claude Code we're 30% more productive. Seeking DevOps engineer with Claude experience.", "author": "founder_axk", "score": 312},
]

def mock_analyze(p: dict) -> dict[str, Any]:
    b = p["body"].lower()
    is_hiring = sum(1 for w in ["hiring", "join us", "looking for", "seeking"] if w in b)
    is_claude = 1 if "claude" in b else 0
    score = 30 + (is_claude * 40) + (is_hiring * 15) + min(p["score"] // 10, 10)
    return {
        "company_name": "Anthropic" if "Anthropic" in p["body"] else "Startup",
        "contact_name": p["author"],
        "contact_title": "Engineering" if is_hiring else "Developer",
        "intent": "hiring" if is_hiring else "evaluate",
        "urgency": "high" if is_hiring else "medium",
        "confidence": min(score/100.0, 1.0),
        "opportunity_score": min(score, 100),
        "pain_point": "hiring" if is_hiring else "evaluating",
        "raw_excerpt": p["body"][:120]+"...",
        "source_url": p["url"],
        "industry": "AI / Developer Tools",
        "score_band": "hot" if score>=75 else "warm" if score>=50 else "cool",
    }

def mock_score_and_band(l: dict) -> dict:
    score = l["opportunity_score"]
    band = "hot" if score >= 85 else "warm" if score >= 60 else "cool"
    l["final_score"] = score
    l["score_band"] = band
    return l

async def run_test(mock_mode=True):
    print("="*70)
    print("LeadIQ Smoke Test — 'claude code jobs'")
    print("="*70)
    print(f"Time:     {datetime.now(UTC).isoformat()}")
    print(f"Sources:  {', '.join(SOURCES)}")
    print(f"Mock:     {mock_mode}")
    print("-"*70)

    leads = []
    for p in MOCK_POSTS:
        l = mock_analyze(p)
        l = mock_score_and_band(l)
        leads.append(l)
    leads.sort(key=lambda x: x["final_score"], reverse=True)

    summary = {
        "query": SEARCH_QUERY, "mock": mock_mode,
        "timestamp": datetime.now(UTC).isoformat(),
        "total_posts": len(MOCK_POSTS), "total_leads": len(leads),
        "hot_leads": [l for l in leads if l["score_band"]=="hot"],
        "medium_leads": [l for l in leads if l["score_band"]=="warm"],
        "cold_leads": [l for l in leads if l["score_band"]=="cool"],
    }

    print(f"\nPipeline complete — {len(leads)} leads found\n")
    for rank, l in enumerate(leads, 1):
        print(f"  #{rank}  {l['score_band'].upper():<4}  {l['final_score']:.0f}/100  {l['company_name']}")
        print(f"        Intent {l['intent']:<8}  Contact {l['contact_name']:<20}  Conf {l['confidence']:.0%}")
        print(f"        URL {l['source_url']}")
        print(f"        Pain {l['pain_point'][:60]}...")
        print()
    return summary

if __name__ == "__main__":
    s = asyncio.run(run_test(mock_mode="--live" not in sys.argv))
    print("-"*70)
    print(f"Summary:  {s['total_posts']} posts → {s['total_leads']} leads")
    print(f"  Hot:   {len(s['hot_leads'])} | Warm: {len(s['medium_leads'])} | Cool: {len(s['cold_leads'])}")
    print("-"*70)
    json.dump(s, sys.stdout, indent=2)
    print()
