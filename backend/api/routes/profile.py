"""
api/routes/profile.py — User profile CRUD + personalised lead recommendations.

GET  /api/profile                → retrieve active profile (or defaults)    [open]
POST /api/profile                → create / update active profile           [auth]
GET  /api/profile/leads          → leads ranked by personalised score       [open]
GET  /api/profile/mode-templates → return starter templates per mode        [open]
GET  /api/profile/velocity       → top companies by signal velocity         [open]
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from backend.api.deps import DbSession, CurrentUser
from backend.api.schemas import (
    PersonalizedLeadOut,
    UserProfileRequest,
    UserProfileResponse,
)
from backend.services.personalization import (
    build_personalized_results,
    OperationMode,
)
from backend.services.velocity import velocity_tracker
from backend.shared.repository import LeadRepo, ProfileRepo

router = APIRouter(prefix="/api/profile", tags=["profile"])


# ── Default profile returned when none exists yet ─────────────────────────────

def _default_profile_response() -> UserProfileResponse:
    return UserProfileResponse(
        id=0,
        mode=OperationMode.B2B_SALES,
        product_description=None,
        target_customer=None,
        target_industries=[],
        target_company_sizes=[],
        include_keywords=[],
        exclude_keywords=[],
        hiring_roles=[],
        skills=[],
        min_salary=0,
        remote_only=False,
        feedback_adjustments={},
        updated_at=datetime.now(UTC),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=UserProfileResponse)
async def get_profile(session: DbSession) -> UserProfileResponse:
    """Return the active user profile. If none exists, return sensible defaults."""
    repo    = ProfileRepo(session)
    profile = await repo.get_active()
    if not profile:
        return _default_profile_response()
    return UserProfileResponse.model_validate(profile)


@router.post("/", response_model=UserProfileResponse, status_code=200)
async def upsert_profile(
    body: UserProfileRequest,
    session: DbSession,
    _user: CurrentUser,                      # ← requires valid JWT
) -> UserProfileResponse:
    """Create or fully replace the active profile. Triggers rescoring on next request."""
    repo = ProfileRepo(session)
    data = body.model_dump()
    profile = await repo.upsert(data)
    return UserProfileResponse.model_validate(profile)


@router.get("/leads", response_model=list[PersonalizedLeadOut])
async def personalised_leads(
    session: DbSession,
    limit: int = Query(50, ge=1, le=200),
    min_base_score: float = Query(0.0, ge=0.0, le=100.0),
) -> list[PersonalizedLeadOut]:
    """Return leads ranked by personalised score with real-time velocity annotations."""
    profile_repo = ProfileRepo(session)
    lead_repo    = LeadRepo(session)

    profile = await profile_repo.get_active()
    profile_data: dict = {}
    if profile:
        profile_data = {
            "mode":                 profile.mode,
            "target_industries":    profile.target_industries   or [],
            "target_company_sizes": profile.target_company_sizes or [],
            "include_keywords":     profile.include_keywords    or [],
            "exclude_keywords":     profile.exclude_keywords    or [],
            "feedback_adjustments": profile.feedback_adjustments or {},
        }

    leads = await lead_repo.list_all(min_score=min_base_score, limit=500)
    company_names = [l.company_name for l in leads if l.company_name]
    velocity_map  = await velocity_tracker.get_velocity_map(company_names)

    return await build_personalized_results(leads, profile_data, velocity_map, limit)


@router.get("/velocity")
async def velocity_top() -> dict:
    """Return top companies by cross-source signal count (7-day rolling window)."""
    top = await velocity_tracker.get_top_companies(limit=20)
    return {"companies": top, "window_days": 7}


@router.get("/mode-templates")
async def mode_templates() -> dict:
    """
    Return pre-filled profile starter templates for each operation mode.
    Frontend can show these as one-click quickstart options.
    """
    return {
        "b2b_sales": {
            "mode":                 "b2b_sales",
            "product_description":  "We build [your product description here]",
            "target_customer":      "Founders and engineering managers at Series A–B SaaS startups",
            "target_industries":    ["saas", "devtools", "fintech"],
            "target_company_sizes": ["startup", "smb"],
            "include_keywords":     ["looking for", "recommend", "frustrated", "switching"],
            "exclude_keywords":     ["student", "homework", "academic"],
            "hiring_roles":         [],
            "skills":               [],
        },
        "hiring": {
            "mode":                 "hiring",
            "product_description":  "",
            "target_customer":      "Fast-growing tech startups with open engineering roles",
            "target_industries":    ["saas", "ai", "devtools"],
            "target_company_sizes": ["startup", "smb"],
            "include_keywords":     ["hiring", "join our team", "open position", "Series A"],
            "exclude_keywords":     ["internship", "unpaid"],
            "hiring_roles":         ["senior engineer", "backend engineer", "full-stack"],
            "skills":               [],
        },
        "job_search": {
            "mode":                 "job_search",
            "product_description":  "",
            "target_customer":      "Companies with strong engineering culture and competitive comp",
            "target_industries":    ["saas", "fintech", "ai"],
            "target_company_sizes": ["startup", "smb", "enterprise"],
            "include_keywords":     ["remote", "equity", "flexible"],
            "exclude_keywords":     ["no remote", "on-site required"],
            "hiring_roles":         [],
            "skills":               ["python", "typescript", "react", "fastapi"],
            "remote_only":          True,
            "min_salary":           120000,
        },
        "opportunity": {
            "mode":                 "opportunity",
            "product_description":  "",
            "target_customer":      "Underserved markets with clear pain points",
            "target_industries":    ["ai", "devtools", "saas", "marketplace"],
            "target_company_sizes": ["startup"],
            "include_keywords":     ["problem", "pain point", "wish there was", "market gap"],
            "exclude_keywords":     [],
            "hiring_roles":         [],
            "skills":               [],
        },
    }



# ── Default profile returned when none exists yet ─────────────────────────────

def _default_profile_response() -> UserProfileResponse:
    return UserProfileResponse(
        id=0,
        mode=OperationMode.B2B_SALES,
        product_description=None,
        target_customer=None,
        target_industries=[],
        target_company_sizes=[],
        include_keywords=[],
        exclude_keywords=[],
        hiring_roles=[],
        skills=[],
        min_salary=0,
        remote_only=False,
        feedback_adjustments={},
        updated_at=datetime.now(UTC),
    )

