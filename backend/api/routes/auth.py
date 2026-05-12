"""
api/routes/auth.py — Authentication endpoints.

POST /api/auth/login    → exchange credentials for JWT pair
POST /api/auth/refresh  → exchange refresh token for new access token
GET  /api/auth/me       → verify token + return current username
POST /api/auth/logout   → client-side logout hint (no server state)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.api.deps import OptionalUser
from backend.services.auth import (
    create_access_token,
    create_refresh_token,
    revoke_token,
    verify_credentials,
    verify_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 60 * 8   # seconds — informational


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class MeResponse(BaseModel):
    username: str
    authenticated: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """
    Exchange username + password for a JWT access + refresh token pair.
    Rate-limited by slowapi at the app level (10/minute).
    """
    if not verify_credentials(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token  = create_access_token(body.username),
        refresh_token = create_refresh_token(body.username),
        expires_in    = 60 * 8,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair.
    The old refresh token is revoked after successful verification."""
    try:
        username = verify_token(body.refresh_token, expected_type="refresh")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Revoke the used refresh token to prevent replay attacks
    revoke_token(body.refresh_token)

    return TokenResponse(
        access_token  = create_access_token(username),
        refresh_token = create_refresh_token(username),
        expires_in    = 60 * 8,
    )


@router.get("/me", response_model=MeResponse)
async def me(user: OptionalUser) -> MeResponse:
    """
    Verify the access token from the Authorization header and return the username.
    """
    if not user:
        return MeResponse(username="", authenticated=False)
    return MeResponse(username=user, authenticated=True)


@router.post("/logout")
async def logout(body: LogoutRequest) -> dict:
    """
    Revoke the provided refresh token server-side so it can no longer be used.
    Clients should still delete stored tokens locally.
    """
    if body.refresh_token:
        revoke_token(body.refresh_token)
    return {"detail": "Logged out. Delete stored tokens client-side."}
