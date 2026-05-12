"""
services/personalization.py — Adaptive personalization engine.

THE core differentiator. LeadIQ adapts ALL collection, scoring, and outreach
to the user's specific goals, ICP, and learned preferences.

Modes (mutually exclusive, switchable at any time):
  b2b_sales    — find companies with buying intent matching your product
  hiring       — find fast-growing companies actively hiring in your target role
  job_search   — find open positions matching your skills + company preferences
  opportunity  — detect emerging market gaps and rising demand trends

Three-layer architecture:
  Layer 1 — Query Generation  : profile → dynamic search queries per collector
  Layer 2 — Profile-Fit Score : how well this lead matches user preferences
  Layer 3 — Feedback Learning : cumulative rating history shifts scoring weights

Additional signals:
  Temporal Decay   : fresh signals score higher (7-day half-life)
  Keyword Boost    : include_keywords add up to +10 pts per match
  Velocity Tracker : cross-platform topic frequency amplifies urgency
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from backend.api.schemas import LeadOut, PersonalizedLeadOut


# ── Operation Modes ───────────────────────────────────────────────────────────

class OperationMode:
    B2B_SALES   = "b2b_sales"
    HIRING      = "hiring"
    JOB_SEARCH  = "job_search"
    OPPORTUNITY = "opportunity"
    ALL         = ["b2b_sales", "hiring", "job_search", "opportunity"]


# ── Query Generator ───────────────────────────────────────────────────────────

class QueryGenerator:
    """
    Translates a UserProfile into concrete search queries per collector.
    Called by collect_and_publish() to make collection profile-aware.
    Queries are source-specific (Reddit, HN, ProductHunt, StackOverflow, etc.).
    """

    # ── Base query sets per mode ───────────────────────────────────────────────

    _B2B_BASES = [
        "looking for software recommendation",
        "recommend a tool for",
        "need help with automation",
        "pain point workflow",
        "anyone use SaaS for",
        "frustrated with current solution",
        "switching from",
        "alternatives to",
        "vendor comparison",
        "budget for software",
        "ROI software",
        "outgrowing our current tool",
    ]

    _HIRING_BASES = [
        "we are hiring",
        "join our team",
        "open position",
        "Series A hiring",
        "scaling engineering team",
        "growing startup team",
        "remote hiring",
        "technical co-founder",
        "head of engineering",
    ]

    _JOB_BASES = [
        "we are looking for",
        "open role",
        "hiring engineer",
        "software engineer remote",
        "full-time opportunity",
        "backend developer position",
        "frontend developer position",
        "product manager role",
    ]

    _OPPORTUNITY_BASES = [
        "nobody is solving",
        "underserved market",
        "gap in the market",
        "micro-SaaS opportunity",
        "market disruption",
        "growing demand for",
        "problem with existing tools",
        "wish someone would build",
        "no good solution for",
        "I built this because",
    ]

    # ── Industry → subreddit mapping ───────────────────────────────────────────

    _INDUSTRY_SUBREDDITS: dict[str, list[str]] = {
        "fintech":     ["fintech", "personalfinance", "investing"],
        "devtools":    ["devops", "programming", "softwaretesting"],
        "healthcare":  ["healthIT", "EHR", "medicine"],
        "ecommerce":   ["ecommerce", "shopify", "dropship"],
        "marketing":   ["marketing", "PPC", "SEO", "socialmedia"],
        "hr":          ["humanresources", "recruitinghell", "jobs"],
        "saas":        ["SaaS", "startups", "entrepreneur"],
        "ai":          ["MachineLearning", "LocalLLaMA", "artificial"],
        "crypto":      ["CryptoCurrency", "defi", "web3"],
        "education":   ["edtech", "learnprogramming", "OnlineLearning"],
        "legal":       ["legaladvice", "lawyers"],
        "real_estate": ["realestateinvesting", "RealEstate"],
        "logistics":   ["supplychain", "logistics"],
    }

    _MODE_SUBREDDITS: dict[str, list[str]] = {
        OperationMode.B2B_SALES: [
            "entrepreneur", "startups", "SaaS", "smallbusiness",
            "marketing", "sales", "b2bsales", "webdev", "devops", "aws",
        ],
        OperationMode.HIRING: [
            "startups", "entrepreneur", "cscareerquestions",
            "remotework", "remotejobs", "sysadmin", "devops",
        ],
        OperationMode.JOB_SEARCH: [
            "cscareerquestions", "remotejobs", "forhire", "jobsearchhacks",
            "remotework", "learnprogramming", "webdev", "Python",
        ],
        OperationMode.OPPORTUNITY: [
            "entrepreneur", "startups", "smallbusiness", "freelance",
            "SideProject", "indiehackers", "nocode", "Entrepreneur",
        ],
    }

    def generate_reddit_queries(
        self,
        mode: str,
        include_keywords: list[str],
        target_industries: list[str],
        hiring_roles: list[str],
        skills: list[str],
    ) -> list[str]:
        """Build search queries for each target subreddit."""
        bases = list(self._bases_for_mode(mode))
        queries = list(bases)

        for kw in include_keywords[:6]:
            queries.append(f"looking for {kw}")
            queries.append(f"recommend {kw} tool")

        for industry in target_industries[:3]:
            queries.append(f"{industry} software")
            queries.append(f"need tool for {industry}")

        for role in hiring_roles[:3]:
            queries.append(f"hiring {role}")

        for skill in skills[:3]:
            queries.append(f"hiring {skill} engineer")
            queries.append(f"{skill} role remote")

        return _dedup(queries)[:15]

    def generate_subreddits(
        self,
        mode: str,
        target_industries: list[str],
    ) -> list[str]:
        """Return the subreddit list to scrape."""
        base = list(self._MODE_SUBREDDITS.get(mode, self._MODE_SUBREDDITS[OperationMode.B2B_SALES]))
        for industry in target_industries:
            extras = self._INDUSTRY_SUBREDDITS.get(industry.lower(), [])
            base.extend(extras)
        return _dedup(base)[:14]

    def generate_hn_queries(
        self,
        mode: str,
        include_keywords: list[str],
        target_industries: list[str],
        skills: list[str],
    ) -> list[str]:
        """HN Algolia queries."""
        if mode == OperationMode.B2B_SALES:
            queries = [
                "Ask HN: looking for",
                "Ask HN: recommend",
                "Ask HN: alternatives to",
                "Ask HN: how do you",
                "frustrated with",
                "switched from",
                "seeking product",
                "who wants to hire",
            ]
        elif mode == OperationMode.HIRING:
            queries = [
                "Ask HN: Who is hiring",
                "YC backed hiring",
                "remote hiring startup",
                "who wants to be hired",
            ]
        elif mode == OperationMode.JOB_SEARCH:
            queries = [
                "Ask HN: Who wants to be hired",
                "Ask HN: Who is hiring",
                "open positions remote",
                "software engineer hiring",
            ]
        else:  # OPPORTUNITY
            queries = [
                "Ask HN: What problems",
                "Ask HN: Is there a tool",
                "Ask HN: How do you deal with",
                "wish someone would build",
                "market opportunity",
                "nobody has solved",
            ]

        for kw in include_keywords[:3]:
            queries.append(kw)
        for industry in target_industries[:2]:
            queries.append(f"{industry} tool")
        for skill in skills[:2]:
            queries.append(skill)

        return _dedup(queries)[:12]

    def generate_github_labels(self, mode: str) -> list[str]:
        if mode == OperationMode.JOB_SEARCH:
            return ["good first issue", "looking for contributor", "help wanted"]
        return ["help wanted", "question", "bug", "discussion"]

    def _bases_for_mode(self, mode: str) -> list[str]:
        return {
            OperationMode.B2B_SALES:   self._B2B_BASES,
            OperationMode.HIRING:      self._HIRING_BASES,
            OperationMode.JOB_SEARCH:  self._JOB_BASES,
            OperationMode.OPPORTUNITY: self._OPPORTUNITY_BASES,
        }.get(mode, self._B2B_BASES)


# ── Temporal Decay ────────────────────────────────────────────────────────────

def compute_temporal_decay(collected_at_iso: str, half_life_days: float = 7.0) -> float:
    """
    Exponential decay weight: 1.0 for fresh signals, ~0.10 for very old ones.

    Formula: w = e^(-ln(2) * age_days / half_life_days)
    Half-life 7 days: a week-old signal is worth half a fresh one.
    Floor at 0.10 — old signals still carry 10% weight (long-tail value).
    """
    try:
        collected_at = datetime.fromisoformat(collected_at_iso)
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - collected_at).total_seconds() / 86400.0
        decay = math.exp(-math.log(2) * max(0.0, age_days) / half_life_days)
        return max(0.10, round(decay, 4))
    except Exception:
        return 0.70  # safe default if parsing fails


# ── Profile-Fit Scorer ────────────────────────────────────────────────────────

def compute_profile_fit(
    industry: str | None,
    company_size: str | None,
    intent: str,
    profile_data: dict[str, Any],
) -> float:
    """
    How well does this lead match the user's saved profile?
    Returns a multiplier in [0.50 … 1.50].

    > 1.0 = stronger-than-average fit → boosts final score
    < 1.0 = weaker-than-average fit   → reduces final score
    """
    target_industries: list[str] = profile_data.get("target_industries", [])
    target_sizes: list[str]      = profile_data.get("target_company_sizes", [])
    mode: str                    = profile_data.get("mode", OperationMode.B2B_SALES)

    if not target_industries and not target_sizes:
        # No preferences → neutral, only apply mode-intent alignment
        multiplier = 1.0
    else:
        checks  = 0
        matches = 0

        if target_industries and industry:
            checks += 1
            if any(t.lower() in industry.lower() for t in target_industries):
                matches += 1

        if target_sizes and company_size:
            checks += 1
            if company_size in target_sizes:
                matches += 1

        fit_ratio  = (matches / checks) if checks > 0 else 0.5
        multiplier = 1.0 + (fit_ratio - 0.5) * 0.40  # range [0.80 … 1.20]

    # Mode-intent alignment bonus/penalty
    if mode == OperationMode.B2B_SALES:
        if intent in ("buy", "pain"):
            multiplier += 0.15
        elif intent == "other":
            multiplier -= 0.10
    elif mode == OperationMode.HIRING:
        if intent in ("buy", "evaluate"):
            multiplier += 0.10
    elif mode == OperationMode.JOB_SEARCH:
        multiplier += 0.08   # job search: all leads broadly relevant

    return max(0.50, min(1.50, round(multiplier, 4)))


# ── Feedback Learning ─────────────────────────────────────────────────────────

_RATING_DELTA: dict[int, float] = {5: +0.12, 4: +0.06, 3: 0.0, 2: -0.06, 1: -0.12}


def record_feedback(
    adjustments: dict[str, float],
    industry: str | None,
    intent: str,
    rating: int,
) -> dict[str, float]:
    """
    Record a human rating and update the learning weights.

    Key = "{industry}:{intent}" → float in [-0.30, +0.30].
    Positive = "show me more like this", Negative = "less of this".
    """
    key   = f"{(industry or 'unknown').lower()}:{intent}"
    delta = _RATING_DELTA.get(rating, 0.0)
    prev  = adjustments.get(key, 0.0)
    adjustments[key] = max(-0.30, min(0.30, prev + delta))
    return adjustments


def get_feedback_adjustment(
    adjustments: dict[str, float],
    industry: str | None,
    intent: str,
) -> float:
    """Retrieve the learned score delta for this industry+intent pair. 0.0 if unseen."""
    key = f"{(industry or 'unknown').lower()}:{intent}"
    return adjustments.get(key, 0.0)


# ── Keyword Signals ───────────────────────────────────────────────────────────

def passes_keyword_filter(text: str, exclude_keywords: list[str]) -> bool:
    """Hard blocklist: return False if any exclude keyword appears in text."""
    text_lower = text.lower()
    for kw in exclude_keywords:
        if kw.lower() in text_lower:
            return False
    return True


def keyword_boost(text: str, include_keywords: list[str]) -> float:
    """
    Soft boost from matching include_keywords.
    Each match adds +2 pts (max +10 total).
    """
    text_lower = text.lower()
    matches = sum(1 for kw in include_keywords if kw.lower() in text_lower)
    return min(10.0, matches * 2.0)


# ── Signal Velocity ───────────────────────────────────────────────────────────

def velocity_bonus(cross_source_count: int) -> float:
    """
    Bonus for signals appearing across multiple sources/platforms.
    Same company on Twitter + Reddit + HN = high velocity = urgent signal.

    cross_source_count = 1 → 0 pts (baseline)
    cross_source_count = 2 → +5 pts
    cross_source_count = 3 → +10 pts
    cross_source_count ≥4  → +15 pts (capped)
    """
    return min(15.0, max(0.0, (cross_source_count - 1) * 5.0))


# ── Composite Personalized Score ─────────────────────────────────────────────

def compute_personalized_score(
    base_final_score: float,
    collected_at_iso: str,
    industry: str | None,
    company_size: str | None,
    intent: str,
    text_for_keywords: str,
    profile_data: dict[str, Any],
    cross_source_count: int = 1,
) -> dict[str, float]:
    """
    Compute the full personalized score from a base score + all adjustments.

    Returns a breakdown dict with:
      personalized_score, temporal_decay, profile_fit,
      keyword_bonus, feedback_bonus, velocity_bonus
    """
    decay    = compute_temporal_decay(collected_at_iso)
    fit      = compute_profile_fit(industry, company_size, intent, profile_data)

    include_kw  = profile_data.get("include_keywords", [])
    feedback_adj = profile_data.get("feedback_adjustments", {})

    kw_bonus  = keyword_boost(text_for_keywords, include_kw)
    fb_raw    = get_feedback_adjustment(feedback_adj, industry, intent)
    fb_bonus  = fb_raw * 100.0  # [-30 … +30]
    vel_bonus = velocity_bonus(cross_source_count)

    # Temporal and fit are applied as additive bonuses centred at 0
    temporal_bonus = (decay - 0.50) * 20.0   # [-8 … +10]
    fit_bonus      = (fit - 1.00) * 20.0     # [-10 … +10]

    p_score = base_final_score + temporal_bonus + fit_bonus + kw_bonus + fb_bonus + vel_bonus
    p_score = max(0.0, min(100.0, round(p_score, 1)))

    return {
        "personalized_score": p_score,
        "temporal_decay":     round(decay, 4),
        "profile_fit":        round(fit, 4),
        "keyword_bonus":      round(kw_bonus, 1),
        "feedback_bonus":     round(fb_bonus, 1),
        "velocity_bonus":     round(vel_bonus, 1),
    }


# ── Personalized Lead Builder ─────────────────────────────────────────────────

async def build_personalized_results(
    leads: list[Any],
    profile_data: dict[str, Any],
    velocity_map: dict[str, int],
    limit: int = 50,
) -> list[PersonalizedLeadOut]:
    """
    Score and rank leads using profile fit, temporal decay, keywords,
    feedback learning, and cross-source velocity.
    """
    exclude_kw: list[str] = profile_data.get("exclude_keywords", [])
    result: list[PersonalizedLeadOut] = []

    for lead in leads:
        signal_text = " ".join(filter(None, [
            lead.company_name, lead.industry, lead.intent,
            getattr(lead, "post", None) and getattr(lead.post, "body", None) or "",
        ]))
        if exclude_kw and not passes_keyword_filter(signal_text, exclude_kw):
            continue

        collected_iso = (
            lead.created_at.isoformat()
            if lead.created_at
            else datetime.now(UTC).isoformat()
        )
        cross_source_count = velocity_map.get(lead.company_name or "", 0)

        breakdown = compute_personalized_score(
            base_final_score=lead.final_score,
            collected_at_iso=collected_iso,
            industry=lead.industry,
            company_size=lead.company_size,
            intent=lead.intent or "other",
            text_for_keywords=signal_text,
            profile_data=profile_data,
            cross_source_count=cross_source_count,
        )

        base_out = LeadOut.model_validate(lead)
        result.append(PersonalizedLeadOut(
            **base_out.model_dump(),
            personalized_score=breakdown["personalized_score"],
            temporal_decay=breakdown["temporal_decay"],
            profile_fit=breakdown["profile_fit"],
            keyword_bonus=breakdown["keyword_bonus"],
            feedback_bonus=breakdown["feedback_bonus"],
            velocity_bonus=breakdown["velocity_bonus"],
        ))

    result.sort(key=lambda x: x.personalized_score, reverse=True)
    return result[:limit]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dedup(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
