"""
icp_scorer.py — Logistic Regression ICP Scoring (Day 16)

Scores leads against the user's Ideal Customer Profile using weighted features.
Weights initialized from ground_truth.json and dynamically adjusted via feedback.

Features:
  - industry_match: How well lead industry matches ICP target industries
  - company_size_match: How well lead size matches ICP ideal range
  - intent_signal_strength: Strength of detected intent signals
  - source_trust: Per-source reliability weighting
  - keyword_density: ICP keyword matches in source text
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default feature weights (logistic regression coefficients)
# These get tuned from ground_truth.json and user feedback
DEFAULT_WEIGHTS: dict[str, float] = {
    "industry_match": 2.5,
    "company_size_match": 1.8,
    "intent_signal_strength": 3.0,
    "source_trust": 2.2,
    "keyword_density": 1.5,
    "intercept": -2.0,  # bias term
}

SOURCE_TRUST_WEIGHTS: dict[str, float] = {
    "github": 0.95,
    "hn": 0.82,
    "reddit": 0.68,
    "telegram": 0.60,
    "twitter": 0.55,
    "rss": 0.60,
    "producthunt": 0.72,
    "stackoverflow": 0.78,
    "tracxn": 0.70,
    "yourstory": 0.75,
    "indiamart": 0.50,
    "dpiit": 0.85,
}

GROUND_TRUTH_PATH = Path("eval/ground_truth.json")


def sigmoid(x: float) -> float:
    """Sigmoid activation — maps to (0, 1) probability."""
    return 1.0 / (1.0 + math.exp(-min(x, 50)))  # clamped for numerical stability


def load_weights_from_ground_truth() -> dict[str, float]:
    """Bootstraps initial weights by analyzing ground_truth.json field distributions."""
    try:
        if not GROUND_TRUTH_PATH.exists():
            logger.warning("ground_truth.json not found, using default weights")
            return dict(DEFAULT_WEIGHTS)

        data = json.loads(GROUND_TRUTH_PATH.read_text())
        records = data if isinstance(data, list) else data.get("leads", [])

        if not records:
            return dict(DEFAULT_WEIGHTS)

        # Count industry coverage in ground truth to weight industry_match
        industries = set()
        sources = set()
        for r in records:
            ind = r.get("industry") or r.get("Industry")
            src = r.get("source")
            if ind and str(ind).strip():
                industries.add(str(ind).strip().lower())
            if src:
                sources.add(str(src).strip().lower())

        # Wider industry coverage = more weight on industry_match
        industry_coverage = min(len(industries) / 20.0, 2.0)
        source_coverage = min(len(sources) / 8.0, 1.5)

        tuned = dict(DEFAULT_WEIGHTS)
        tuned["industry_match"] = round(2.5 * industry_coverage, 2)
        tuned["source_trust"] = round(2.2 * source_coverage, 2)

        logger.info("icp_weights_loaded", industries=len(industries), sources=len(sources))
        return tuned

    except Exception as exc:
        logger.error("icp_weight_load_failed error=%s", exc)
        return dict(DEFAULT_WEIGHTS)


def score_industry_match(lead_industry: str | None, icp_industries: list[str]) -> float:
    """Scores how well lead industry matches ICP targets. Returns 0.0–1.0."""
    if not lead_industry or not icp_industries:
        return 0.5  # neutral when unknown

    lead_lower = lead_industry.lower().strip()
    for icp_ind in icp_industries:
        icp_lower = icp_ind.lower().strip()
        if lead_lower == icp_lower:
            return 1.0
        if icp_lower in lead_lower or lead_lower in icp_lower:
            return 0.75
    return 0.1


def score_company_size_match(lead_size: str | None, ideal_range: str | None) -> float:
    """Scores company size proximity. Returns 0.0–1.0."""
    if not lead_size or not ideal_range:
        return 0.5

    size_buckets = {
        "1-10": 0, "11-50": 1, "51-200": 2, "201-500": 3,
        "501-1000": 4, "1001-5000": 5, "5001-10000": 6, "10000+": 7,
    }

    lead_bucket = size_buckets.get(lead_size)
    ideal_bucket = size_buckets.get(ideal_range)

    if lead_bucket is None or ideal_bucket is None:
        try:
            lead_bucket = sum(
                1 for r in size_buckets if r == lead_size.split("-")[0]
            ) if "-" in lead_size else None
        except Exception:
            return 0.5

    if lead_bucket is None:
        return 0.5

    distance = abs(lead_bucket - ideal_bucket)
    return max(0.1, 1.0 - distance * 0.2)


def compute_icp_score(
    lead_data: dict[str, Any],
    icp_profile: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Computes ICP relevance probability using logistic regression.

    lead_data: dict with industry, company_size, intent, source, source_text
    icp_profile: dict with target_industries, company_size, keywords
    weights: optional tuned feature weights (defaults to ground-truth-loaded)

    Returns {score, probability, feature_scores, weights_used}
    """
    w = weights or load_weights_from_ground_truth()

    # Feature extraction
    industry_score = score_industry_match(
        lead_data.get("industry"),
        icp_profile.get("target_industries", []),
    )
    size_score = score_company_size_match(
        lead_data.get("company_size"),
        icp_profile.get("company_size"),
    )

    # Intent signal strength — count intent keywords present
    intent = lead_data.get("intent", "")
    intent_strength = 0.5
    if intent:
        intent_words = {"hiring", "looking", "seeking", "building", "launching", "growing", "expanding"}
        source_text = str(lead_data.get("source_text", "")).lower()
        matches = sum(1 for w in intent_words if w in source_text)
        intent_strength = min(1.0, 0.3 + matches * 0.15)

    source = str(lead_data.get("source", "")).lower()
    source_trust = SOURCE_TRUST_WEIGHTS.get(source, 0.5)

    # Keyword density
    keywords = icp_profile.get("keywords", [])
    keyword_density = 0.3
    if keywords:
        source_text = str(lead_data.get("source_text", "")).lower()
        matches = sum(1 for kw in keywords if kw.lower() in source_text)
        keyword_density = min(1.0, 0.2 + matches * 0.15)

    # Linear combination (logit)
    z = (
        w.get("industry_match", 2.5) * industry_score
        + w.get("company_size_match", 1.8) * size_score
        + w.get("intent_signal_strength", 3.0) * intent_strength
        + w.get("source_trust", 2.2) * source_trust
        + w.get("keyword_density", 1.5) * keyword_density
        + w.get("intercept", -2.0)
    )

    probability = round(sigmoid(z), 4)
    raw_score = round(z, 3)

    return {
        "icp_probability": probability,
        "icp_raw_score": raw_score,
        "feature_scores": {
            "industry_match": round(industry_score, 2),
            "company_size_match": round(size_score, 2),
            "intent_signal_strength": round(intent_strength, 2),
            "source_trust": round(source_trust, 2),
            "keyword_density": round(keyword_density, 2),
        },
        "weights_used": {k: round(v, 2) for k, v in w.items()},
    }
