"""
backend/services/anomaly_detector.py -- Anomaly Detection for Lead Data Quality

Detects statistical outliers and unusual patterns in lead data including volume
spikes/drops, source distribution imbalances, field completeness issues, and
duplicate rate anomalies.

Usage:
    from backend.services.anomaly_detector import AnomalyDetector, AnomalyReport

    detector = AnomalyDetector()
    anomalies = await detector.detect_anomalies(leads)
    for report in anomalies:
        logger.warning("anomaly_detected", type=report.type, severity=report.severity)
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# Field types used for numeric z-score analysis
NUMERIC_FIELDS: frozenset[str] = frozenset({
    "confidence", "salary_min", "salary_max", "founded_year",
    "company_size", "employee_count", "revenue", "funding_amount",
})


@dataclass
class AnomalyReport:
    """Report of a single detected anomaly.

    Attributes:
        type: Category of anomaly (e.g. 'volume_spike', 'source_dominance').
        severity: Impact level — 'low', 'medium', or 'high'.
        field: The field or dimension where the anomaly was found (optional).
        details: Human-readable description of the anomaly.
        score: Numeric severity score between 0.0 and 1.0.
        action: Suggested remediation action.
    """
    type: str
    severity: str
    details: str
    score: float
    field: str | None = None
    action: str = "review"


class AnomalyDetector:
    """Detect anomalies in lead data using statistical methods.

    Checks performed:
        - Volume anomalies (z-score vs baseline)
        - Source distribution imbalance
        - Field completeness rates
        - Duplicate rates
        - Numeric field outliers (z-score)
    """

    def __init__(self) -> None:
        """Initialise the anomaly detector with default baselines."""
        self.baselines: dict[str, float] = {
            "volume": 1000.0,
            "duplicate_rate": 0.05,
            "completeness_rate": 0.70,
        }

    async def detect_anomalies(self, leads: list[dict[str, Any]]) -> list[AnomalyReport]:
        """Run all anomaly detection checks on a batch of leads.

        Args:
            leads: List of lead dictionaries to analyse.

        Returns:
            List of AnomalyReport instances for each detected anomaly.
        """
        if not leads:
            logger.debug("anomaly_detector_empty_batch")
            return []

        anomalies: list[AnomalyReport] = []

        # Volume anomaly
        if report := self._check_volume_anomaly(leads):
            anomalies.append(report)

        # Source distribution anomaly
        if report := self._check_source_distribution(leads):
            anomalies.append(report)

        # Field completeness anomaly
        if report := self._check_field_completeness(leads):
            anomalies.append(report)

        # Duplicate rate anomaly
        if report := self._check_duplicate_rate(leads):
            anomalies.append(report)

        # Numeric field z-score anomalies
        for field in NUMERIC_FIELDS:
            if report := self._check_numeric_field_anomaly(leads, field):
                anomalies.append(report)

        if anomalies:
            logger.info(
                "anomalies_detected",
                count=len(anomalies),
                batch_size=len(leads),
                severities=[a.severity for a in anomalies],
            )

        return anomalies

    # ── Volume Anomaly ─────────────────────────────────────────────────────────

    def _check_volume_anomaly(self, leads: list[dict[str, Any]]) -> AnomalyReport | None:
        """Detect unusual lead volume (spike or drop) compared to baseline.

        Args:
            leads: List of lead dictionaries.

        Returns:
            AnomalyReport if volume is anomalous, None otherwise.
        """
        count = len(leads)
        baseline = self.baselines.get("volume", 1000.0)

        if count == 0:
            return None

        ratio = count / baseline

        if ratio > 5.0:
            return AnomalyReport(
                type="volume_spike",
                severity="high",
                details=f"Volume {count} is {ratio:.1f}x the baseline of {baseline:.0f}",
                score=min(ratio / 10.0, 1.0),
                action="investigate_source_collectors",
            )

        if ratio < 0.1:
            return AnomalyReport(
                type="volume_drop",
                severity="high",
                details=f"Volume {count} is only {ratio:.1%} of the baseline of {baseline:.0f}",
                score=max(1.0 - ratio, 0.5),
                action="check_collector_health",
            )

        return None

    # ── Source Distribution Anomaly ────────────────────────────────────────────

    def _check_source_distribution(self, leads: list[dict[str, Any]]) -> AnomalyReport | None:
        """Detect source distribution imbalance.

        Flags if a single source accounts for more than 80% of leads.

        Args:
            leads: List of lead dictionaries.

        Returns:
            AnomalyReport if a source dominates, None otherwise.
        """
        total = len(leads)
        if total == 0:
            return None

        source_counts: Counter[str] = Counter()
        for lead in leads:
            source = lead.get("source", "unknown")
            source_counts[source] += 1

        for source, count in source_counts.items():
            ratio = count / total
            if ratio > 0.8:
                return AnomalyReport(
                    type="source_dominance",
                    severity="medium",
                    field="source",
                    details=f"Source '{source}' accounts for {ratio:.1%} of {total} leads",
                    score=ratio,
                    action="verify_source_diversification",
                )

        return None

    # ── Field Completeness Anomaly ─────────────────────────────────────────────

    def _check_field_completeness(self, leads: list[dict[str, Any]]) -> AnomalyReport | None:
        """Detect field completeness issues.

        Flags if more than 30% of leads are missing critical fields like
        company_name.

        Args:
            leads: List of lead dictionaries.

        Returns:
            AnomalyReport if completeness is low, None otherwise.
        """
        total = len(leads)
        if total == 0:
            return None

        missing_company = 0
        missing_email = 0

        for lead in leads:
            raw_meta = lead.get("raw_meta") or {}
            company_name = raw_meta.get("company_name") or lead.get("company_name")
            if not company_name:
                missing_company += 1

            if not lead.get("email"):
                missing_email += 1

        # Check company name completeness
        company_missing_ratio = missing_company / total
        if company_missing_ratio > 0.3:
            return AnomalyReport(
                type="low_completeness",
                severity="medium",
                field="company_name",
                details=f"{company_missing_ratio:.1%} of leads ({missing_company}/{total}) missing company name",
                score=company_missing_ratio,
                action="improve_parsing_or_enrichment",
            )

        # Check email completeness
        email_missing_ratio = missing_email / total
        if email_missing_ratio > 0.7:
            return AnomalyReport(
                type="low_completeness",
                severity="medium",
                field="email",
                details=f"{email_missing_ratio:.1%} of leads ({missing_email}/{total}) missing email",
                score=email_missing_ratio,
                action="check_enrichment_pipeline",
            )

        return None

    # ── Duplicate Rate Anomaly ─────────────────────────────────────────────────

    def _check_duplicate_rate(self, leads: list[dict[str, Any]]) -> AnomalyReport | None:
        """Detect high duplicate rates in lead batch.

        Uses content_hash if available, otherwise falls back to external_id.

        Args:
            leads: List of lead dictionaries.

        Returns:
            AnomalyReport if duplicate rate exceeds threshold, None otherwise.
        """
        total = len(leads)
        if total == 0:
            return None

        # Try content_hash first, fall back to external_id
        hashes: list[str] = []
        for lead in leads:
            h = lead.get("content_hash") or lead.get("external_id") or str(lead.get("id", ""))
            hashes.append(h)

        unique = len(set(hashes))
        duplicate_ratio = 1.0 - (unique / total)

        baseline = self.baselines.get("duplicate_rate", 0.05)

        if duplicate_ratio > baseline * 2 and duplicate_ratio > 0.10:
            return AnomalyReport(
                type="high_duplicate_rate",
                severity="high" if duplicate_ratio > 0.3 else "medium",
                details=f"{duplicate_ratio:.1%} duplicate rate ({total - unique} duplicates in {total} leads)",
                score=duplicate_ratio,
                action="tune_dedup_thresholds",
            )

        return None

    # ── Numeric Field Z-Score Anomaly ──────────────────────────────────────────

    def _check_numeric_field_anomaly(
        self,
        leads: list[dict[str, Any]],
        field: str,
    ) -> AnomalyReport | None:
        """Detect outliers in a numeric field using z-score.

        Values with |z-score| > 3 are flagged as outliers.

        Args:
            leads: List of lead dictionaries.
            field: Field name to analyse.

        Returns:
            AnomalyReport if outliers found, None otherwise.
        """
        values: list[float] = []
        for lead in leads:
            raw = lead.get(field) or (lead.get("raw_meta") or {}).get(field)
            if raw is not None:
                try:
                    values.append(float(raw))
                except (ValueError, TypeError):
                    pass

        if len(values) < 5:
            return None  # Too few data points for meaningful z-score

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return None  # No variance, no outliers

        outliers = [(v, (v - mean) / std_dev) for v in values if abs((v - mean) / std_dev) > 3.0]

        if outliers:
            outlier_count = len(outliers)
            outlier_pct = outlier_count / len(values)
            return AnomalyReport(
                type="field_outliers",
                severity="medium" if outlier_pct < 0.05 else "high",
                field=field,
                details=f"Found {outlier_count} outliers ({outlier_pct:.1%}) in field '{field}', "
                        f"mean={mean:.2f}, std={std_dev:.2f}",
                score=min(outlier_pct * 5, 1.0),
                action=f"validate_{field}_data_source",
            )

        return None

    # ── Baselines ──────────────────────────────────────────────────────────────

    def set_baseline(self, key: str, value: float) -> None:
        """Set or update a baseline value for anomaly comparison.

        Args:
            key: Baseline name (e.g. 'volume', 'duplicate_rate').
            value: Baseline value.
        """
        self.baselines[key] = value
        logger.info("anomaly_baseline_set", key=key, value=value)

    def get_baselines(self) -> dict[str, float]:
        """Get all current baseline values.

        Returns:
            Copy of the baselines dictionary.
        """
        return dict(self.baselines)
