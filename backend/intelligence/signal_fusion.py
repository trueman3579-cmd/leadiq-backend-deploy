"""
backend/intelligence/signal_fusion.py — Multi-source signal fusion engine.
Inspired by WorldMonitor's multi-source signal fusion (correlation across sources).
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class FusedSignal:
    """A cross-source verified signal."""
    signal_id: str
    entities: list[str]  # Companies, people, technologies mentioned
    sources: list[str]  # Source names
    events: list[dict]  # Raw events from each source
    confidence: int = 0  # 0-100 fusion confidence
    anomaly_score: float = 0.0  # Temporal anomaly score
    fusion_score: int = 0  # Composite cross-source score


class SignalFusionEngine:
    """Detects cross-source correlations and amplifies signals."""

    def __init__(self, lookback_hours: int = 72) -> None:
        self._lookback = lookback_hours
        self._recent_signals: list[dict] = []

    def add_signal(self, entity: str, source: str, text: str, score: int) -> None:
        """Add a signal for potential fusion."""
        self._recent_signals.append({
            "entity": entity.lower().strip(),
            "source": source,
            "text": text,
            "score": score,
            "timestamp": datetime.now(UTC),
        })

    def detect_convergence(self) -> list[FusedSignal]:
        """Find entities mentioned in 3+ sources within lookback period."""
        entity_sources: dict[str, list] = defaultdict(list)
        
        for signal in self._recent_signals:
            entity_sources[signal["entity"]].append(signal)

        fused: list[FusedSignal] = []
        for entity, events in entity_sources.items():
            if len(events) >= 3:
                sources = list(set(e["source"] for e in events))
                if len(sources) >= 2:  # At least 2 different sources
                    fs = FusedSignal(
                        signal_id=self._hash_signal(entity, events),
                        entities=[entity],
                        sources=sources,
                        events=events,
                        confidence=min(len(sources) * 20 + len(events) * 10, 100),
                        anomaly_score=len(events) / 10,
                        fusion_score=min(len(sources) * 20 + len(events) * 5 + sum(e["score"] for e in events) / len(events), 100),
                    )
                    fused.append(fs)
                    logger.info(
                        "Fused signal: %s across %d sources (confidence: %d)",
                        entity, len(sources), fs.confidence,
                    )
        
        return sorted(fused, key=lambda x: x.fusion_score, reverse=True)

    @staticmethod
    def _hash_signal(entity: str, events: list) -> str:
        hasher = hashlib.sha256()
        hasher.update(entity.encode())
        hasher.update(str(len(events)).encode())
        hasher.update(events[0]["text"][:50].encode())
        return hasher.hexdigest()[:12]

    def apply_fusion_boost(self, score: int, entities: list[str]) -> int:
        """Apply cross-source fusion boost to a score."""
        for signal in self._recent_signals:
            for entity in entities:
                if signal["entity"] == entity.lower().strip():
                    # Boost by 10-20 points based on cross-source evidence
                    boost = min(len(set(s["source"] for s in self._recent_signals if s["entity"] == entity)) * 5, 20)
                    score = min(score + boost, 100)
        return score
