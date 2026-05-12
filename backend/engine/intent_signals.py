"""
engine/intent_signals.py — 12-Dimensional Intent Signal Extractor
Detects signals in raw text using keyword + context heuristics.
Zero cost, deterministic, extensible.
"""
from __future__ import annotations
import re
import math


class DimensionExtractor:
    def __init__(self, name: str, weight: float, keywords: list[str], contexts: list[str]):
        self.name = name
        self.base_weight = weight
        self.keywords = [kw.lower() for kw in keywords]
        self.context_patterns = [re.compile(p, re.I) for p in contexts]

    def score(self, text: str) -> tuple[int, dict]:
        lower = text.lower()
        keyword_hits = sum(1 for kw in self.keywords if kw in lower)
        context_hits = sum(1 for p in self.context_patterns if p.search(text))

        if keyword_hits == 0 and context_hits == 0:
            return 0, {}

        raw = min(keyword_hits * 20 + context_hits * 30 + 15, 100)
        return raw, {"hits": keyword_hits + context_hits}


# 12 intent signal extractors
EXTRACTORS: dict[str, DimensionExtractor] = {
    "pain_explicit": DimensionExtractor(
        "pain_explicit", 15, [
            "issue", "problem", "struggling", "pain", "frustrated", "broken",
            "annoying", "slow", "unreliable", "too expensive", "waste of money",
            "can't figure out", "doesn't work", "failed to", "terrible",
            "bug", "crash", "error", "timeout", "outage", "down", "broke",
            "this sucks", "ridiculous", "impossible", "hopeless", "nightmare",
        ], [
            r"(?:I'?m|we'?re)\s+(?:having|facing|dealing with)\s+(?:an?\s+)?(?:\w+\s+)?(?:issue|problem)",
            r"(?:looking for|need)\s+(?:a|an)\s+(?:\w+\s+){0,3}(?:solution|fix|alternative)\b",
            r"(?:tried|trying)\s+.{0,50}(?:didn'?t work|failed|too slow|too expensive)",
            r"\b(?:bug|issue)\s+#\d+\b",
        ]
    ),
    "hiring_intent": DimensionExtractor(
        "hiring_intent", 12, [
            "hiring", "we're hiring", "join our team", "open position",
            "looking for", "opportunities", "recruiting", "talent",
            "engineering team", "growing our team", "expanding team",
            "job opening", "job posting", "open role", "apply now",
            "come work", "work with us", "careers page",
        ], [
            r"(?:we'?re|we are)\s+(?:hiring|recruiting|growing|expanding)\b",
            r"(?:join|apply for)\s+(?:our|the)\s+(?:team|company|startup)\b",
            r"(?:job|position|role)\s+(?:opening|available|open|posted)\b",
            r"hiring\s+(?:a|an|senior|junior|lead|staff|principal)\b",
        ]
    ),
    "tech_growth": DimensionExtractor(
        "tech_growth", 15, [
            "migrating to", "switching to", "moved to", "adopting",
            "implementing", "adopted", "migrated", "considering",
            "deploying", "moving to", "next.js", "svelte", "astro",
            "kubernetes", "docker", "terraform", "supabase"
        ], [
            r"(?:migrating|moved|switching)\s+(?:our|from|to)\s+.{0,20}(?:React|Next\.?js|Vue|Angular|Svelte|Astro|Go|Rust|Kubernetes)\b",
            r"adopting\s+(?:React|Next\.?js|Vue|Angular|Svelte|Astro|Go|Rust|Kubernetes)\b"
        ]
    ),
    "budget_signals": DimensionExtractor(
        "budget_signals", 18, [
            "budget", "budgeting", "spending on", "investing in", "funding",
            "pricing", "cost", "roi", "worth the money", "cheaper alternative",
            "cost effective", "allocating", "dollar"
        ], [
            r"(?:our|the)\s+budget\s+(?:is|for)\s+(?:this|that)\s+\$?[\d,]+(?:K|M)?\b",
            r"(?:spending|investing)\s+\$?[\d,]+(?:K|M)?\s+(?:on|in)\s+\w+"
        ]
    ),
    "user_growth": DimensionExtractor(
        "user_growth", 10, [
            "scaling", "scale up", "user growth", "traffic spike", "growing fast",
            "viral", "exploding", "huge demand", "too many users", "MAU",
            "kpi", "growth rate"
        ], [
            r"(?:scaling|growing)\s+(?:to|from|up)\s+.{0,20}(?:users|customers|MAU|visitors)\b",
            r"(?:traffic|demand)\s+(?:spike|surge|growth)\s+(?:of|by|to)\s+\d+%?\b"
        ]
    ),
    "champion_risk": DimensionExtractor(
        "champion_risk", 15, [
            "left", "departed", "former", "ex-", "no longer with",
            "moved on", "transitioning", "stepping down"
        ], [
            r"(?:former|ex[ -])(?:CTO|VP|Director|Engineering Manager)\b",
            r"(?:left|departed|\bleft\s+(?:our|the))\s+(?:company|team|role)\b"
        ]
    ),
    "competitive_indicators": DimensionExtractor(
        "competitive_indicators", 10, [
            "vs", "versus", "compared to", "switching from", "moving away from",
            "left", "dropped", "stopped using", "migrated from", "alternative"
        ], [
            r"(?:compared to|vs\.?)\s+(?:\w+\s+){1,3}(?:Apollo|ZoomInfo|Salesforce|HubSpot|Airtable|Slack)\b",
            r"(?:switching|moving)\s+(?:away from|from)\s+(?:\w+\s+){1,3}(?:Apollo|ZoomInfo|Salesforce)\b"
        ]
    ),
    "urgency": DimensionExtractor(
        "urgency", 8, [
            "asap", "urgent", "deadline", "immediately", "this week",
            "by friday", "by monday", "by tomorrow", "production", "critical",
            "blocking", "stuck", "cannot wait"
        ], [
            r"(?:need|needed|require|required)\s+(?:it|this|that)\s+(?:by|before|within)\s+(?:tomorrow|friday|monday|end of)\b",
            r"(?:deadline|deadline for this)\s+(?:is|was)\s+(?:tomorrow|this week|next week)\b"
        ]
    ),
    "category_momentum": DimensionExtractor(
        "category_momentum", 5, [
            "trending in", "everyone", "growing trend", "market shift",
            "industry moving to", "consensus", "standardizing on"
        ], [
            r"(?:trending|growing|market|industry)\s+(?:in|moving toward|shifting to|standardizing on)\b"
        ]
    ),
    "community_sentiment": DimensionExtractor(
        "community_sentiment", 5, [
            "love this", "hate", "terrible", "amazing", "great tool",
            "best experience", "worst experience", "highly recommend", "avoid"
        ], [
            r"(?:love|hate|recommend|avoid)\s+(?:this|this tool|that tool|our platform|this product)\b",
            r"(?:best|worst|most|least)\s+(?:tool|platform|experience|solution)\b"
        ]
    ),
    "decision_maker_present": DimensionExtractor(
        "decision_maker_present", 8, [
            "CTO", "VP", "Director", "Head of", "VP Engineering",
            "Chief Technology Officer", "VP Product", "Product Manager",
            "Engineering Manager", "Lead Engineer"
        ], [
            r"(?:our|the)\s+(?:CTO|VP|Director|Head of)\b",
            r"(?:as a|I'm a|we're the)\s+(?:CTO|VP|Director|Head)\b"
        ]
    ),
    "funding_runway": DimensionExtractor(
        "funding_runway", 10, [
            "series", "funding", "burn rate", "run out", "raised",
            "investment", "runway", "valuation", "pre-seed", "seed",
            "series A", "series B", "series C", "IPO", "exit"
        ], [
            r"(?:raised|secured)\s+(?:\$[\d,]+(?:K|M|B)?|Series)\b",
            r"(?:burn rate|run out of money|runway)\s+(?:of|is)\s+(?:\d+\s+(?:months|days)|US\$[\d.]+(?:[KM])?)\b"
        ]
    ),
    "engagement_depth": DimensionExtractor(
        "engagement_depth", 7, [
            "deep dive", "evaluating", "researching", "benchmarking",
            "pilot", "proof of concept", " POC ", "testing", "trial",
            "comparing", "assessing", "reviewing"
        ], [
            r"(?:doing a|conducting a)\s+(?:deep dive|evaluation|pilot|benchmark)\b",
            r"(?:pilot|trial|proof of concept)\s+(?:program|phase|test)\b"
        ]
    ),
    "source_reputation": DimensionExtractor(
        "source_reputation", 5, [
            "recommended", "authoritative", "trusted", "popular", "well-known",
            "highly rated", "top rated"
        ], [
            r"(?:highly|well)\s*rated\b",
            r"(?:trusted|authoritative|popular)\s+(?:by|source|source of|among)\b"
        ]
    ),
}


def detect_source_reputation(source: str) -> int:
    reputation_map = {
        "hn": 95, "github": 90, "reddit": 70,
        "stackoverflow": 80, "twitter": 60, "linkedin": 75,
        "producthunt": 65, "indiehacker": 55, "rss": 50, "trello": 40,
    }
    return reputation_map.get(source.lower(), 50)


def calculate_freshness_multiplier(days_old: int) -> float:
    return math.exp(-0.693 * days_old / 7)
