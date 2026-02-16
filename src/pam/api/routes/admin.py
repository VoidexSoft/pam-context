"""Admin routes — user and role management."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pam.api.auth import require_admin
from pam.api.deps import get_db
from pam.api.pagination import PaginatedResponse
from pam.common.models import (
    AssignRoleRequest,
    MessageResponse,
    Project,
    ProjectRoleResponse,
    RoleAssignedResponse,
    User,
    UserProjectRole,
    UserResponse,
    UserWithRoles,
)

logger = structlog.get_logger()

router = APIRouter()


@router.get("/admin/users", response_model=PaginatedResponse[UserResponse])
async def list_users(
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User | None = Depends(require_admin),
):
    """List all users with cursor-based pagination."""
    # Count total
    count_result = await db.execute(select(func.count()).select_from(User))
    total = count_result.scalar() or 0

    # Fetch page
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(limit))
    items = [UserResponse.model_validate(u) for u in result.scalars().all()]

    return PaginatedResponse(items=items, total=total, cursor="")


@router.get("/admin/users/{user_id}", response_model=UserWithRoles)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User | None = Depends(require_admin),
):
    """Get user details with project roles."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.project_roles).selectinload(UserProjectRole.project))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    roles = [
        ProjectRoleResponse(
            project_id=pr.project_id,
            project_name=pr.project.name if pr.project else "Unknown",
            role=pr.role,
        )
        for pr in user.project_roles
    ]
    return UserWithRoles(**UserResponse.model_validate(user).model_dump(), roles=roles)


@router.post("/admin/roles", status_code=201, response_model=RoleAssignedResponse)
async def assign_role(
    request: AssignRoleRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User | None = Depends(require_admin),
):
    """Assign a role to a user for a project."""

    # Validate user and project exist
    user = await db.get(User, request.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    project = await db.get(Project, request.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Upsert role
    result = await db.execute(
        select(UserProjectRole).where(
            UserProjectRole.user_id == request.user_id,
            UserProjectRole.project_id == request.project_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.role = request.role
    else:
        db.add(
            UserProjectRole(
                user_id=request.user_id,
                project_id=request.project_id,
                role=request.role,
            )
        )

    await db.commit()
    logger.info("role_assigned", user_id=str(request.user_id), project_id=str(request.project_id), role=request.role)
    return {"message": "Role assigned", "role": request.role}


@router.delete("/admin/roles/{user_id}/{project_id}", status_code=204)
async def revoke_role(
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User | None = Depends(require_admin),
):
    """Remove a user's role for a project."""
    result = await db.execute(
        delete(UserProjectRole).where(
            UserProjectRole.user_id == user_id,
            UserProjectRole.project_id == project_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Role assignment not found")
    await db.commit()


@router.patch("/admin/users/{user_id}/deactivate", response_model=MessageResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User | None = Depends(require_admin),
):
    """Deactivate a user account."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await db.commit()
    return {"message": "User deactivated"}
