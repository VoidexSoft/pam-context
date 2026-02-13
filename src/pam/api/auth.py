"""JWT token generation, validation, and auth dependencies."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pam.api.deps import get_db
from pam.common.config import settings
from pam.common.models import User, UserProjectRole

logger = structlog.get_logger()

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    """Create a signed JWT for the given user."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def _get_current_user_from_token(
    db: AsyncSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User | None:
    """Extract and validate user from Bearer token. Returns None if auth is disabled."""
    if not settings.auth_required:
        return None

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(
        select(User)
        .options(selectinload(User.project_roles).selectinload(UserProjectRole.project))
        .where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User | None:
    """FastAPI dependency: returns current authenticated user, or None if auth disabled."""
    if not settings.auth_required:
        return None
    return await _get_current_user_from_token(db, credentials)


async def require_auth(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """FastAPI dependency: requires authentication. Raises 401 if auth enabled and no valid user."""
    if settings.auth_required and user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    if user is None:
        # Auth disabled — return a placeholder for type safety
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Auth disabled but require_auth called")
    return user


def require_role(required_role: str):
    """Factory: returns a dependency that checks if the user has the given role for a project.

    Usage: Depends(require_role("admin"))
    The route must accept a project_id parameter.
    """

    async def _check_role(
        request: Request,
        user: Annotated[User | None, Depends(get_current_user)],
    ) -> User | None:
        if not settings.auth_required:
            return None

        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        # Extract project_id from path or query params
        project_id = request.path_params.get("project_id") or request.query_params.get("project_id")
        if project_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id required")

        role_hierarchy = {"viewer": 0, "editor": 1, "admin": 2}
        required_level = role_hierarchy.get(required_role, 0)

        for pr in user.project_roles:
            if str(pr.project_id) == str(project_id):
                user_level = role_hierarchy.get(pr.role, -1)
                if user_level >= required_level:
                    return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires '{required_role}' role for this project",
        )

    return _check_role


async def require_admin(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User | None:
    """FastAPI dependency: requires admin role on any project. Returns None if auth disabled."""
    if not settings.auth_required:
        return None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    if not any(pr.role == "admin" for pr in user.project_roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def get_user_project_ids(user: User | None) -> list[uuid.UUID] | None:
    """Get list of project IDs the user has access to. Returns None if auth disabled."""
    if user is None:
        return None  # No filtering when auth disabled
    return [pr.project_id for pr in user.project_roles]
