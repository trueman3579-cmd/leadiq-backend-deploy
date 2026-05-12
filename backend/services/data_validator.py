"""
backend/services/data_validator.py -- Automated Data Validation for Lead Quality

Provides schema validation, format checks (email, phone, GST, PAN, CIN, Udyam),
content quality checks, and source-specific validation rules for lead data.

Usage:
    from backend.services.data_validator import DataValidator, ValidationResult

    validator = DataValidator()
    result = await validator.validate_lead(lead)
    if result.is_valid:
        ...
    else:
        for error in result.errors:
            logger.warning("validation_error", error=error)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


# ── Validation Result ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Result of a lead validation.

    Attributes:
        is_valid: True if the lead passes all validation checks.
        errors: List of error messages (validation failures).
        warnings: List of warning messages (non-blocking concerns).
        score: Overall quality score between 0.0 and 1.0.
    """
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float = 1.0


# ── Validation Patterns ────────────────────────────────────────────────────────────

# Email: basic RFC 5322 simplified pattern
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Indian phone: 10 digits optionally preceded by +91 or 0
INDIAN_PHONE_PATTERN = re.compile(r"^(\+91|91|0)?[6-9]\d{9}$")

# GST: 2 state + 10 PAN + 1 entity + 3 checksum + 1 check (Z = default check char)
GST_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$")

# PAN: 5 letters + 4 digits + 1 letter
PAN_PATTERN = re.compile(r"^[A-Z]{5}\d{4}[A-Z]{1}$")

# CIN: 1 letter + 5 digits + 2 letters + 4 digits + 3 digits + 6 chars
CIN_PATTERN = re.compile(r"^[A-Z]{1}\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")

# Udyam: 12-digit Udyam Registration Number (UDYAM-XX-00-0000000)
UDYAM_PATTERN = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")

# Valid sources from the ingestion pipeline
VALID_SOURCES: frozenset[str] = frozenset({
    "naukri", "internshala", "linkedin", "indeed", "shine", "monster",
    "freshersworld", "hirist", "cutshort", "angellist", "instahyre",
    "dpiit", "mca21", "gem", "msme", "reddit", "hn", "github",
    "stackoverflow", "twitter", "telegram", "producthunt", "rss",
    "tracxn", "indimart", "github_profile", "yourstory", "hacker_news",
    "llm_web_scrape", "llm_vision", "hunter_io", "crunchbase",
    "justdial", "generic_web", "linkedin_api", "github_api",
})

# Fields considered essential for a valid lead
REQUIRED_FIELDS: frozenset[str] = frozenset({"source", "external_id", "title"})


# ── Validator ──────────────────────────────────────────────────────────────────────

class DataValidator:
    """Validate lead data quality through schema, format, and content checks.

    Performs:
        - Required field presence checks
        - Source-specific format validation
        - Contact information format validation (email, phone)
        - Indian business identifier validation (GST, PAN, CIN, Udyam)
        - Content quality heuristics
        - Cross-field consistency checks
    """

    async def validate_lead(self, lead: dict[str, Any]) -> ValidationResult:
        """Validate a single lead dictionary.

        Args:
            lead: Lead data dictionary to validate.

        Returns:
            A ValidationResult with validation outcome.
        """
        errors: list[str] = []
        warnings: list[str] = []
        checks_passed = 0
        checks_total = 0

        # ── Required Fields ───────────────────────────────────────────────────────
        checks_total += 1
        missing_required = REQUIRED_FIELDS - set(lead.keys())
        if missing_required:
            errors.append(f"Missing required fields: {', '.join(sorted(missing_required))}")
        else:
            checks_passed += 1

        # Validate source
        source = lead.get("source", "")
        if source:
            checks_total += 1
            if source not in VALID_SOURCES:
                warnings.append(f"Unknown source '{source}' — may not be handled by pipeline")
            else:
                checks_passed += 1

        # Validate external_id
        external_id = lead.get("external_id", "")
        if external_id:
            checks_total += 1
            if external_id == "unknown" or external_id == "":
                errors.append("external_id is 'unknown' or empty — cannot deduplicate")
            else:
                checks_passed += 1

        # Validate title
        title = lead.get("title", "")
        if title:
            checks_total += 1
            stripped = title.strip()
            if len(stripped) < 3:
                errors.append("Title is too short (minimum 3 characters)")
            elif len(stripped) > 500:
                errors.append("Title is too long (maximum 500 characters)")
            else:
                checks_passed += 1
        elif missing_required:
            pass  # already reported above

        # ── Contact Information ────────────────────────────────────────────────────
        email = lead.get("email")
        if email:
            checks_total += 1
            if not self.validate_email(email):
                errors.append(f"Invalid email format: {email}")
            else:
                checks_passed += 1

        phone = lead.get("phone")
        if phone:
            checks_total += 1
            if not self.validate_phone(phone):
                warnings.append(f"Unusual phone format: {phone}")
            else:
                checks_passed += 1

        # ── Content Quality ────────────────────────────────────────────────────────
        body = lead.get("body") or ""
        if body:
            checks_total += 1
            if len(body.strip()) < 20:
                warnings.append("Body content is very short (under 20 characters)")
            else:
                checks_passed += 1

        # Contact information presence heuristic
        checks_total += 1
        has_contact = bool(
            lead.get("email")
            or lead.get("website")
            or lead.get("company_website")
            or lead.get("linkedin_url")
        )
        if not has_contact:
            warnings.append("No contact information found (email, website, or LinkedIn)")
        else:
            checks_passed += 1

        # ── Source-Specific Checks ─────────────────────────────────────────────────
        raw_meta = lead.get("raw_meta") or {}
        company_name = raw_meta.get("company_name") or lead.get("company_name")

        if source in ("naukri", "internshala", "linkedin"):
            checks_total += 1
            if not company_name:
                errors.append(f"Job lead from '{source}' is missing company_name")
            else:
                checks_passed += 1

        if source in ("dpiit", "mca21", "gem", "msme"):
            checks_total += 1
            if not company_name:
                errors.append(f"Government lead from '{source}' is missing company_name")
            else:
                checks_passed += 1

        # ── Cross-Field Validation ─────────────────────────────────────────────────
        salary_min = raw_meta.get("salary_min")
        salary_max = raw_meta.get("salary_max")
        if salary_min is not None and salary_max is not None:
            checks_total += 1
            try:
                if float(salary_min) > float(salary_max):
                    errors.append(f"Salary min ({salary_min}) exceeds salary max ({salary_max})")
                else:
                    checks_passed += 1
            except (ValueError, TypeError):
                errors.append("Salary fields are not valid numbers")

        # ── Business Identifier Validation ────────────────────────────────────────
        gst = raw_meta.get("gst") or lead.get("gst")
        if gst:
            checks_total += 1
            if not self.validate_gst(gst):
                errors.append(f"Invalid GST format: {gst}")
            else:
                checks_passed += 1

        pan = raw_meta.get("pan") or lead.get("pan")
        if pan:
            checks_total += 1
            if not self.validate_pan(pan):
                errors.append(f"Invalid PAN format: {pan}")
            else:
                checks_passed += 1

        cin = raw_meta.get("cin") or lead.get("cin")
        if cin:
            checks_total += 1
            if not self.validate_cin(cin):
                errors.append(f"Invalid CIN format: {cin}")
            else:
                checks_passed += 1

        udyam = raw_meta.get("udyam") or lead.get("udyam")
        if udyam:
            checks_total += 1
            if not self.validate_udyam(udyam):
                errors.append(f"Invalid Udyam format: {udyam}")
            else:
                checks_passed += 1

        # ── Compute Score ──────────────────────────────────────────────────────────
        score = round(checks_passed / max(checks_total, 1), 4)
        is_valid = len(errors) == 0

        if not is_valid:
            logger.debug(
                "lead_validation_failed",
                lead_id=lead.get("id", lead.get("external_id", "unknown")),
                error_count=len(errors),
                warning_count=len(warnings),
                score=score,
            )

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            score=score,
        )

    # ── Format Validators ─────────────────────────────────────────────────────────

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate an email address format.

        Uses a simplified RFC 5322 pattern.

        Args:
            email: Email address string.

        Returns:
            True if the email format is valid.
        """
        if not email or not isinstance(email, str):
            return False
        return bool(EMAIL_PATTERN.match(email.strip()))

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate an Indian phone number format.

        Accepts:
            - 10-digit numbers starting with 6-9
            - With +91, 91, or 0 prefix

        Args:
            phone: Phone number string.

        Returns:
            True if the phone format is valid.
        """
        if not phone or not isinstance(phone, str):
            return False
        return bool(INDIAN_PHONE_PATTERN.match(phone.strip()))

    @staticmethod
    def validate_gst(gst: str) -> bool:
        """Validate a GST (Goods and Services Tax) number format.

        Format: 2 state + 10 PAN + 1 entity + 3 checksum + 1 check char (Z).

        Args:
            gst: GST number string.

        Returns:
            True if the GST format is valid.
        """
        if not gst or not isinstance(gst, str):
            return False
        return bool(GST_PATTERN.match(gst.strip().upper()))

    @staticmethod
    def validate_pan(pan: str) -> bool:
        """Validate a PAN (Permanent Account Number) format.

        Format: 5 letters + 4 digits + 1 letter.

        Args:
            pan: PAN string.

        Returns:
            True if the PAN format is valid.
        """
        if not pan or not isinstance(pan, str):
            return False
        return bool(PAN_PATTERN.match(pan.strip().upper()))

    @staticmethod
    def validate_cin(cin: str) -> bool:
        """Validate a CIN (Corporate Identification Number) format.

        Format: 1 letter + 5 digits + 2 letters + 4 digits + 3 letters + 6 digits.

        Args:
            cin: CIN string.

        Returns:
            True if the CIN format is valid.
        """
        if not cin or not isinstance(cin, str):
            return False
        return bool(CIN_PATTERN.match(cin.strip().upper()))

    @staticmethod
    def validate_udyam(udyam: str) -> bool:
        """Validate an Udyam (MSME registration) number format.

        Format: UDYAM-XX-00-0000000.

        Args:
            udyam: Udyam registration number string.

        Returns:
            True if the Udyam format is valid.
        """
        if not udyam or not isinstance(udyam, str):
            return False
        return bool(UDYAM_PATTERN.match(udyam.strip().upper()))

    # ── Batch Validation ─────────────────────────────────────────────────────────

    async def validate_batch(self, leads: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate a batch of leads and return aggregate statistics.

        Args:
            leads: List of lead dictionaries.

        Returns:
            Dict with 'total', 'valid', 'invalid', 'accuracy', and 'details' keys.
        """
        results: list[dict[str, Any]] = []
        for lead in leads:
            result = await self.validate_lead(lead)
            results.append({
                "lead_id": lead.get("id", lead.get("external_id", "unknown")),
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
                "score": result.score,
            })

        total = len(leads)
        valid_count = sum(1 for r in results if r["is_valid"])
        accuracy = round((valid_count / total) * 100, 2) if total > 0 else 0.0

        logger.info(
            "lead_validation_batch_complete",
            total=total,
            valid=valid_count,
            invalid=total - valid_count,
            accuracy=accuracy,
        )

        return {
            "total": total,
            "valid": valid_count,
            "invalid": total - valid_count,
            "accuracy": accuracy,
            "details": results,
        }
