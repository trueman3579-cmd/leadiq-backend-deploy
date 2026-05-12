"""
api/routes/validate.py — URL trust validation endpoint.

GET /api/validate-url?url=https://example.com → Trust validation result
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.services.url_validator import URLValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["validation"])


class TrustValidationResponse(BaseModel):
    url: str
    domain: str
    score: float
    trust_level: str
    checks: dict
    recommendations: list[str]


_validator = None


def _get_validator():
    global _validator
    if _validator is None:
        _validator = URLValidator()
    return _validator


@router.get("/validate-url", response_model=TrustValidationResponse)
async def validate_url(url: str = Query(..., description="URL to validate")):
    """
    Validate URL trustworthiness.

    Checks:
    - SSL/TLS certificate validity
    - Domain characteristics
    - Government domain detection (.gov.in)
    - Reachability
    """
    validator = _get_validator()
    result = await validator.validate(url)

    return TrustValidationResponse(
        url=result.url,
        domain=result.domain,
        score=result.score,
        trust_level=result.trust_level,
        checks=result.checks,
        recommendations=result.recommendations,
    )
