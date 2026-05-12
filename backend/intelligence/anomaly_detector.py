"""
backend/intelligence/anomaly_detector.py — Temporal anomaly detection engine.
Inspired by WorldMonitor's Welford algorithm for streaming mean/variance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BaselineStats:
    """Running statistics for a single signal type."""
    mean: float = 0.0
    variance: float = 0.0
    count: int = 0
    last_update: datetime = field(default_factory=lambda: datetime.now(UTC))

    def update(self, value: float) -> None:
        """Update mean and variance using Welford's online algorithm."""
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.variance += delta * delta2
        self.last_update = datetime.now(UTC)

    @property
    def std_dev(self) -> float:
        if self.count < 2:
            return 0.0
        return math.sqrt(self.variance / (self.count - 1))

    def z_score(self, value: float) -> float:
        """Calculate z-score for a new value."""
        if self.count < 2:
            return 0.0
        sd = self.std_dev
        if sd == 0:
            return 0.0
        return (value - self.mean) / sd


class AnomalyDetector:
    """Detects temporal anomalies using streaming statistics."""

    def __init__(self, min_samples: int = 10, z_thresholds: dict[str, float] | None = None) -> None:
        self._min_samples = min_samples
        self._z_thresholds = z_thresholds or {
            "low": 1.5,
            "medium": 2.0,
            "high": 3.0,
        }
        self._baselines: dict[str, BaselineStats] = {}

    def record(self, signal_type: str, value: float) -> dict:
        """Record a signal and check for anomalies."""
        if signal_type not in self._baselines:
            self._baselines[signal_type] = BaselineStats()

        baseline = self._baselines[signal_type]
        
        # Check for anomaly BEFORE updating baseline
        anomaly = None
        if baseline.count >= self._min_samples:
            z = baseline.z_score(value)
            severity = self._classify_z_score(z)
            if severity:
                anomaly = {
                    "signal_type": signal_type,
                    "value": value,
                    "z_score": round(z, 2),
                    "mean": round(baseline.mean, 2),
                    "std_dev": round(baseline.std_dev, 2),
                    "severity": severity,
                    "direction": "spike" if z > 0 else "drop",
                }

        # Update baseline after checking
        baseline.update(value)
        
        return anomaly or {}

    def _classify_z_score(self, z: float) -> str | None:
        """Classify z-score severity."""
        abs_z = abs(z)
        if abs_z >= self._z_thresholds["high"]:
            return "high"
        elif abs_z >= self._z_thresholds["medium"]:
            return "medium"
        elif abs_z >= self._z_thresholds["low"]:
            return "low"
        return None

    def get_baseline(self, signal_type: str) -> BaselineStats:
        """Get current baseline stats for a signal type."""
        return self._baselines.get(signal_type, BaselineStats())


# Example usage:
# detector = AnomalyDetector()
# anomaly = detector.record("kubernetes_mentions", 15)  # If normally ~5
# if anomaly:
#     print(f"🚨 Anomaly: {anomaly}")
