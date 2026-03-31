"""Memory CRUD REST endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from pam.api.auth import get_current_user
from pam.common.models import (
    MemoryCreate,
    MemoryResponse,
    MemorySearchResult,
    MemoryUpdate,
    User,
)

router = APIRouter()


def get_memory_service():
    """Dependency stub — overridden at app startup."""
    raise RuntimeError("MemoryService not initialized")


def _require_user(user: User | None) -> User:
    """Raise 401 if no authenticated user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("", response_model=MemoryResponse)
async def store_memory(
    body: MemoryCreate,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """Store a new memory (fact, preference, observation).

    Automatically deduplicates — if a similar memory exists (cosine > 0.9),
    merges the content instead of creating a duplicate.
    """
    owner = _require_user(user)
    return await memory_service.store(
        content=body.content,
        memory_type=body.type,
        source=body.source,
        metadata=body.metadata,
        importance=body.importance,
        user_id=owner.id,
        project_id=body.project_id,
        expires_at=body.expires_at,
    )


@router.get("/search", response_model=list[MemorySearchResult])
async def search_memories(
    query: str,
    project_id: uuid.UUID | None = None,
    type: str | None = None,
    top_k: int = 10,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """Semantic search across the authenticated user's memories."""
    owner = _require_user(user)
    return await memory_service.search(
        query=query,
        user_id=owner.id,
        project_id=project_id,
        type_filter=type,
        top_k=min(top_k, 50),
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: uuid.UUID,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """Get a specific memory by ID (must belong to authenticated user)."""
    owner = _require_user(user)
    result = await memory_service.get(memory_id)
    if result is None or result.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """Update a memory's content, metadata, or importance."""
    owner = _require_user(user)
    # Verify ownership before updating
    existing = await memory_service.get(memory_id)
    if existing is None or existing.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    result = await memory_service.update(
        memory_id=memory_id,
        content=body.content,
        metadata=body.metadata,
        importance=body.importance,
        expires_at=body.expires_at if "expires_at" in body.model_fields_set else None,
        clear_expires_at="expires_at" in body.model_fields_set and body.expires_at is None,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: uuid.UUID,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """Delete a memory (must belong to authenticated user)."""
    owner = _require_user(user)
    # Verify ownership before deleting
    existing = await memory_service.get(memory_id)
    if existing is None or existing.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    await memory_service.delete(memory_id)
    return {"message": "Memory deleted", "id": str(memory_id)}


@router.get("/user/{user_id}", response_model=list[MemoryResponse])
async def list_user_memories(
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    type: str | None = None,
    limit: int = 50,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """List all memories for a user (must be the authenticated user)."""
    owner = _require_user(user)
    if user_id != owner.id:
        raise HTTPException(status_code=403, detail="Cannot access another user's memories")
    return await memory_service.list_by_user(
        user_id=user_id,
        project_id=project_id,
        type_filter=type,
        limit=min(limit, 200),
    )
