"""Auth routes — Google OAuth2 login and token management."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.auth import create_access_token, get_current_user
from pam.api.deps import get_db
from pam.common.config import settings
from pam.common.models import TokenResponse, User, UserResponse

logger = structlog.get_logger()

router = APIRouter()


class GoogleAuthRequest(BaseModel):
    """Exchange a Google OAuth2 ID token for a PAM access token."""
    id_token: str


class DevLoginRequest(BaseModel):
    """Dev-only: login with just an email (no OAuth). Only works when auth_required=False."""
    email: str
    name: str = "Dev User"


@router.post("/auth/google", response_model=TokenResponse)
async def google_login(
    request: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange Google ID token for a PAM JWT access token."""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        idinfo = google_id_token.verify_oauth2_token(
            request.id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as e:
        logger.warning("google_auth_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid Google ID token")

    email = idinfo.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in Google token")

    # Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            name=idinfo.get("name", email),
            picture=idinfo.get("picture"),
            google_id=idinfo.get("sub"),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("user_created", email=email)
    else:
        # Update profile info
        user.name = idinfo.get("name", user.name)
        user.picture = idinfo.get("picture", user.picture)
        user.google_id = idinfo.get("sub", user.google_id)
        await db.commit()

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/auth/dev-login", response_model=TokenResponse)
async def dev_login(
    request: DevLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Dev-only login endpoint. Only available when AUTH_REQUIRED=false."""
    if settings.auth_required:
        raise HTTPException(status_code=403, detail="Dev login disabled in production")

    # Find or create user
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=request.email, name=request.name)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/auth/me", response_model=UserResponse)
async def get_me(
    user: User | None = Depends(get_current_user),
):
    """Get current user profile. Returns 401 if auth enabled and no valid token."""
    if not settings.auth_required:
        raise HTTPException(status_code=404, detail="Auth not enabled")
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserResponse.model_validate(user)
