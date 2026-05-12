"""
tests/test_personalization.py — Tests for the personalization engine.
Covers: temporal decay, profile fit, feedback learning, keyword filtering,
query generation, and composite score computation.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


from backend.services.personalization import (
    QueryGenerator,
    OperationMode,
    compute_temporal_decay,
    compute_profile_fit,
    compute_personalized_score,
    record_feedback,
    get_feedback_adjustment,
    passes_keyword_filter,
    keyword_boost,
    velocity_bonus,
)


# ── compute_temporal_decay ────────────────────────────────────────────────────

def test_temporal_decay_fresh_signal():
    """Signal collected right now should have decay close to 1.0."""
    iso = datetime.now(UTC).isoformat()
    decay = compute_temporal_decay(iso)
    assert decay >= 0.95, f"Expected ≥0.95 for fresh signal, got {decay}"


def test_temporal_decay_one_week_old():
    """7-day-old signal should have decay close to 0.5 (half-life)."""
    iso = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    decay = compute_temporal_decay(iso)
    assert 0.45 <= decay <= 0.55, f"Expected ~0.5 for 7-day-old signal, got {decay}"


def test_temporal_decay_very_old_signal():
    """Very old signal should be floored at 0.10."""
    iso = (datetime.now(UTC) - timedelta(days=365)).isoformat()
    decay = compute_temporal_decay(iso)
    assert decay == 0.10, f"Expected floor of 0.10, got {decay}"


def test_temporal_decay_bad_input():
    """Invalid ISO string should return safe default."""
    decay = compute_temporal_decay("not-a-date")
    assert decay == 0.70


# ── compute_profile_fit ───────────────────────────────────────────────────────

def test_profile_fit_perfect_industry_match():
    """Matching industry + size should push multiplier above 1.0."""
    profile = {
        "mode": OperationMode.B2B_SALES,
        "target_industries": ["saas", "fintech"],
        "target_company_sizes": ["startup"],
    }
    fit = compute_profile_fit("saas", "startup", "buy", profile)
    assert fit > 1.0, f"Expected >1.0 for perfect match, got {fit}"


def test_profile_fit_no_match():
    """Mismatched industry + size should push multiplier below 1.0."""
    profile = {
        "mode": OperationMode.B2B_SALES,
        "target_industries": ["fintech"],
        "target_company_sizes": ["startup"],
    }
    fit = compute_profile_fit("healthcare", "enterprise", "other", profile)
    assert fit < 1.0, f"Expected <1.0 for mismatch, got {fit}"


def test_profile_fit_no_preferences_neutral():
    """No preferences configured → neutral multiplier (around 1.0)."""
    profile = {"mode": OperationMode.B2B_SALES, "target_industries": [], "target_company_sizes": []}
    fit = compute_profile_fit("saas", "startup", "buy", profile)
    # buy intent in b2b mode adds bonus
    assert fit >= 1.0, f"Expected ≥1.0 with buy intent, got {fit}"


def test_profile_fit_clamps_at_bounds():
    """Fit multiplier must stay in [0.50, 1.50]."""
    profile = {
        "mode": OperationMode.B2B_SALES,
        "target_industries": ["saas"],
        "target_company_sizes": ["startup"],
    }
    fit = compute_profile_fit("saas", "startup", "buy", profile)
    assert 0.50 <= fit <= 1.50


# ── record_feedback + get_feedback_adjustment ─────────────────────────────────

def test_feedback_positive_rating_increases_adjustment():
    adj: dict[str, float] = {}
    adj = record_feedback(adj, "saas", "buy", rating=5)
    val = get_feedback_adjustment(adj, "saas", "buy")
    assert val > 0.0, f"Rating 5 should increase adjustment, got {val}"


def test_feedback_negative_rating_decreases_adjustment():
    adj: dict[str, float] = {}
    adj = record_feedback(adj, "fintech", "other", rating=1)
    val = get_feedback_adjustment(adj, "fintech", "other")
    assert val < 0.0, f"Rating 1 should decrease adjustment, got {val}"


def test_feedback_clamped_at_max():
    adj: dict[str, float] = {}
    for _ in range(30):
        adj = record_feedback(adj, "saas", "buy", rating=5)
    val = get_feedback_adjustment(adj, "saas", "buy")
    assert val <= 0.30, f"Adjustment should be clamped at 0.30, got {val}"


def test_feedback_unknown_key_returns_zero():
    adj: dict[str, float] = {}
    val = get_feedback_adjustment(adj, "unknown_industry", "buy")
    assert val == 0.0


# ── passes_keyword_filter ─────────────────────────────────────────────────────

def test_keyword_filter_passes_when_no_exclusions():
    assert passes_keyword_filter("We need a better CRM", []) is True


def test_keyword_filter_blocks_excluded_term():
    assert passes_keyword_filter("This is a student homework project", ["student", "homework"]) is False


def test_keyword_filter_case_insensitive():
    assert passes_keyword_filter("ENTERPRISE not relevant", ["enterprise"]) is False


# ── keyword_boost ─────────────────────────────────────────────────────────────

def test_keyword_boost_returns_zero_for_no_matches():
    boost = keyword_boost("completely unrelated text", ["saas", "crm"])
    assert boost == 0.0


def test_keyword_boost_awards_points_per_match():
    boost = keyword_boost("looking for a saas crm tool", ["saas", "crm", "looking for"])
    assert boost == 6.0  # 3 matches × 2 pts


def test_keyword_boost_capped_at_10():
    boost = keyword_boost("one two three four five six seven eight nine ten keywords", [str(i) for i in range(20)])
    assert boost <= 10.0


# ── velocity_bonus ────────────────────────────────────────────────────────────

def test_velocity_bonus_single_source():
    assert velocity_bonus(1) == 0.0


def test_velocity_bonus_two_sources():
    assert velocity_bonus(2) == 5.0


def test_velocity_bonus_capped():
    assert velocity_bonus(100) == 15.0


# ── compute_personalized_score ────────────────────────────────────────────────

def test_personalized_score_bounds():
    """Personalized score must always be in [0, 100]."""
    profile = {
        "mode": OperationMode.B2B_SALES,
        "target_industries": ["saas"],
        "target_company_sizes": ["startup"],
        "include_keywords": ["crm"],
        "feedback_adjustments": {},
    }
    result = compute_personalized_score(
        base_final_score=85.0,
        collected_at_iso=datetime.now(UTC).isoformat(),
        industry="saas",
        company_size="startup",
        intent="buy",
        text_for_keywords="looking for a crm tool",
        profile_data=profile,
    )
    assert 0.0 <= result["personalized_score"] <= 100.0
    assert "temporal_decay" in result
    assert "profile_fit" in result
    assert "keyword_bonus" in result
    assert "feedback_bonus" in result


def test_personalized_score_worse_for_old_mismatched_lead():
    """Old, mismatched lead should score lower than fresh, matched one."""
    profile = {
        "mode": OperationMode.B2B_SALES,
        "target_industries": ["saas"],
        "target_company_sizes": ["startup"],
        "include_keywords": [],
        "feedback_adjustments": {},
    }
    fresh_score = compute_personalized_score(
        base_final_score=60.0,
        collected_at_iso=datetime.now(UTC).isoformat(),
        industry="saas",
        company_size="startup",
        intent="buy",
        text_for_keywords="need saas tool",
        profile_data=profile,
    )["personalized_score"]

    old_mismatched = compute_personalized_score(
        base_final_score=60.0,
        collected_at_iso=(datetime.now(UTC) - timedelta(days=30)).isoformat(),
        industry="healthcare",
        company_size="enterprise",
        intent="other",
        text_for_keywords="general discussion",
        profile_data=profile,
    )["personalized_score"]

    assert fresh_score > old_mismatched, (
        f"Fresh matched ({fresh_score}) should beat old mismatched ({old_mismatched})"
    )


# ── QueryGenerator ────────────────────────────────────────────────────────────

def test_query_generator_b2b_returns_queries():
    qg = QueryGenerator()
    queries = qg.generate_reddit_queries(
        mode=OperationMode.B2B_SALES,
        include_keywords=["async", "remote"],
        target_industries=["saas"],
        hiring_roles=[],
        skills=[],
    )
    assert len(queries) >= 5
    assert all(isinstance(q, str) for q in queries)


def test_query_generator_deduplicates():
    qg = QueryGenerator()
    queries = qg.generate_reddit_queries(
        mode=OperationMode.B2B_SALES,
        include_keywords=[],
        target_industries=[],
        hiring_roles=[],
        skills=[],
    )
    assert len(queries) == len(set(queries)), "Queries should be deduplicated"


def test_query_generator_subreddits_by_mode():
    qg = QueryGenerator()
    b2b_subs  = qg.generate_subreddits(OperationMode.B2B_SALES, [])
    job_subs  = qg.generate_subreddits(OperationMode.JOB_SEARCH, [])
    assert "entrepreneur" in b2b_subs
    assert "remotejobs" in job_subs


def test_query_generator_hn_job_search():
    qg = QueryGenerator()
    queries = qg.generate_hn_queries(
        mode=OperationMode.JOB_SEARCH,
        include_keywords=[],
        target_industries=[],
        skills=["python"],
    )
    assert any("hired" in q.lower() or "hiring" in q.lower() for q in queries)
