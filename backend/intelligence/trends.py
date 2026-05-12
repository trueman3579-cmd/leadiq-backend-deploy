"""
backend/intelligence/trends.py — Trend + Topic Modeling Engine
Uses zero-cost BERTopic with DistilBERT embeddings to detect rising topics.
Identifies market shifts, tech adoption curves, and category momentum.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Try to import BERTopic — optional dependency
try:
    from bertopic import BERTopic
    from sentence_transformers import SentenceTransformer
    BERTOPIC_AVAILABLE = True
except ImportError:
    BERTOPIC_AVAILABLE = False
    logger.warning("BERTopic not installed. Running in lightweight mode.")


class TrendAnalyzer:
    """Detects market trends and topic momentum from lead text."""

    def __init__(self) -> None:
        self._model = None
        self._topic_model = None
        if BERTOPIC_AVAILABLE:
            try:
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
                self._topic_model = BERTopic(embedding_model=self._model, min_topic_size=5)
                logger.info("BERTopic initialized with DistilBERT")
            except Exception as e:
                logger.warning("Failed to init BERTopic: %s", e)
                self._model = None
                self._topic_model = None

    def extract_topics(self, texts: list[str]) -> list[dict]:
        """Extract trending topics from lead texts. Returns list of topic dicts."""
        if not self._topic_model or len(texts) < 10:
            # Fallback: keyword frequency analysis
            return self._keyword_trends(texts)

        try:
            topics, probs = self._topic_model.fit_transform(texts)
            topic_info = self._topic_model.get_topic_info()

            results = []
            for _, row in topic_info.iterrows():
                if row["Topic"] == -1:
                    continue
                results.append({
                    "topic_id": row["Topic"],
                    "count": row["Count"],
                    "keywords": [w for w, _ in self._topic_model.get_topic(row["Topic"])][:5],
                    "momentum_score": min(row["Count"] * 10, 100),
                })
            return results
        except Exception as e:
            logger.warning("BERTopic extraction failed: %s", e)
            return self._keyword_trends(texts)

    def _keyword_trends(self, texts: list[str]) -> list[dict]:
        """Lightweight keyword frequency trend analysis."""
        all_text = " ".join(texts).lower()

        # Filter for tech/business keywords only
        tech_keywords = {
            "kubernetes", "docker", "terraform", "aws", "azure", "gcp", "google cloud",
            "react", "next.js", "vue", "angular", "svelte", "astro",
            "python", "go", "rust", "typescript", "javascript",
            "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
            "machine learning", "ai", "ml", "llm", "openai", "anthropic",
            "saas", "b2b", "startup", "funding", "series", "valuation",
            "hiring", "remote", "growth", "scaling", "migration",
        }

        trends = []
        for keyword in tech_keywords:
            count = all_text.count(keyword)
            if count > 0:
                trends.append({
                    "topic_id": keyword,
                    "count": count,
                    "keywords": [keyword],
                    "momentum_score": min(count * 15, 100),
                })

        # Sort by momentum
        trends.sort(key=lambda x: x["momentum_score"], reverse=True)
        return trends[:20]  # Top 20 trends

    def detect_momentum(self, topic_id: str, historical_counts: list[int]) -> str:
        """Classify topic momentum based on historical data."""
        if len(historical_counts) < 2:
            return "INSUFFICIENT_DATA"

        recent = historical_counts[-1]
        previous = historical_counts[-2]

        if previous == 0:
            return "EMERGING" if recent > 0 else "STABLE"

        change = (recent - previous) / previous

        if change > 0.5:
            return "EXPLODING"
        elif change > 0.2:
            return "RISING"
        elif change < -0.3:
            return "DECLINING"
        else:
            return "STABLE"


class SignalAmplifier:
    """Amplifies weak signals by cross-referencing multiple data points."""

    def __init__(self) -> None:
        self._trend_analyzer = TrendAnalyzer()

    def amplify(self, lead: dict, all_posts: list[dict]) -> dict:
        """Find corroborating signals across all posts to boost confidence."""
        company = lead.get("company", "").lower()
        if not company:
            return lead

        # Find other posts about same company
        related = [
            p for p in all_posts
            if company in p.get("title", "").lower() or company in p.get("body", "").lower()
        ]

        if len(related) >= 3:
            lead["amplified_signals"] = len(related)
            lead["amplification_confidence"] = min(len(related) * 10, 100)
            lead["confidence"] = "HOT" if lead.get("overall", 0) > 70 else "WARM"

        return lead
