"""Tests for data validation helpers — email, phone, GST, PAN, CIN formats."""
from __future__ import annotations

import re

import pytest


# ── Validation helpers (self-contained, no external deps) ──────────────────


def validate_email(email: str) -> bool:
    """Basic email format validation."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """Validate Indian phone numbers (+91 or 10-digit starting with 6-9)."""
    cleaned = phone.replace(" ", "").replace("-", "")
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    return bool(re.match(r"^[6-9]\d{9}$", cleaned))


def validate_gst(gst: str) -> bool:
    """Validate Indian GST (15 chars: 2 state + 10 PAN + 1 entity + 1 Z + 1 check + 1 C)."""
    pattern = r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$"
    return bool(re.match(pattern, gst.upper()))


def validate_pan(pan: str) -> bool:
    """Validate Indian PAN (10 chars: 5 letters + 4 digits + 1 letter)."""
    pattern = r"^[A-Z]{5}\d{4}[A-Z]{1}$"
    return bool(re.match(pattern, pan.upper()))


def validate_cin(cin: str) -> bool:
    """Validate Indian CIN (21 chars)."""
    pattern = r"^[A-Z]{1}\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$"
    return bool(re.match(pattern, cin.upper()))


# ── Tests ──────────────────────────────────────────────────────────────────


class TestValidateEmail:
    """Verify email validation for valid and invalid patterns."""

    @pytest.mark.parametrize(
        "email",
        [
            "user@example.com",
            "first.last@company.co.in",
            "user+tag@domain.org",
            "test@sub.domain.io",
            "user_name@domain.net.in",
        ],
    )
    def test_valid_emails(self, email: str) -> None:
        assert validate_email(email) is True

    @pytest.mark.parametrize(
        "email",
        [
            "",
            "not-an-email",
            "@domain.com",
            "user@",
            "user@.com",
            "user@domain",
            "user @domain.com",
        ],
    )
    def test_invalid_emails(self, email: str) -> None:
        assert validate_email(email) is False


class TestValidatePhone:
    """Verify Indian phone number validation."""

    @pytest.mark.parametrize(
        "phone",
        [
            "+919876543210",
            "9876543210",
            "+91 9876543210",
            "+91-9876543210",
            "9988776655",
        ],
    )
    def test_valid_phones(self, phone: str) -> None:
        assert validate_phone(phone) is True

    @pytest.mark.parametrize(
        "phone",
        [
            "",
            "1234567890",  # starts with 1
            "0123456789",  # starts with 0
            "+911234567890",  # starts with 1 after +91
            "98765",  # too short
            "98765432100",  # too long
            "abcdefghij",
        ],
    )
    def test_invalid_phones(self, phone: str) -> None:
        assert validate_phone(phone) is False


class TestValidateGST:
    """Verify GST number format validation."""

    @pytest.mark.parametrize(
        "gst",
        [
            "27AABCD1234E1ZS",
            "29AABCD1234F2ZT",
            "33AABCD1234G3ZU",
        ],
    )
    def test_valid_gst(self, gst: str) -> None:
        assert validate_gst(gst) is True

    @pytest.mark.parametrize(
        "gst",
        [
            "",
            "12345",  # too short
            "27AABCD1234E1Z",  # missing last char
            "27AABCD1234E1ZSA",  # too long
            "aaAABCD1234E1ZS",  # invalid state code prefix
        ],
    )
    def test_invalid_gst(self, gst: str) -> None:
        assert validate_gst(gst) is False


class TestValidatePAN:
    """Verify PAN card format validation."""

    @pytest.mark.parametrize(
        "pan",
        [
            "ABCDE1234F",
            "XYZPQ5678R",
            "AAAAA0000A",
        ],
    )
    def test_valid_pan(self, pan: str) -> None:
        assert validate_pan(pan) is True

    @pytest.mark.parametrize(
        "pan",
        [
            "",
            "ABCDE1234",  # too short (9 chars)
            "ABCDE1234FG",  # too long (11 chars)
            "12345ABCDE",  # digits in wrong positions
            "ABCD@1234F",  # special character
        ],
    )
    def test_invalid_pan(self, pan: str) -> None:
        assert validate_pan(pan) is False


class TestValidateCIN:
    """Verify CIN number format validation."""

    @pytest.mark.parametrize(
        "cin",
        [
            "L12345MH2024PTC123456",
            "U12345DL2024PLC654321",
            "L99999KA2023NGO987654",
        ],
    )
    def test_valid_cin(self, cin: str) -> None:
        assert validate_cin(cin) is True

    @pytest.mark.parametrize(
        "cin",
        [
            "",
            "L12345MH2024PTC",  # truncated
            "12345MH2024PTC123456",  # missing leading letter
            "L12345M2024PTC123456",  # state code too short
            "L12345MH24PTC123456",  # year too short
        ],
    )
    def test_invalid_cin(self, cin: str) -> None:
        assert validate_cin(cin) is False
