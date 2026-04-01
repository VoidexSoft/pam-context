"""Conversation endpoints — CRUD for conversations and messages."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException

from pam.api.auth import get_current_user
from pam.common.config import settings
from pam.common.models import (
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    ConvMessageResponse,
    MessageCreate,
    User,
)

logger = structlog.get_logger()

router = APIRouter()


def get_conversation_service():
    """Dependency stub — overridden at app startup."""
    raise RuntimeError("ConversationService not initialized")


def _require_user(user: User | None) -> User | None:
    """Raise 401 if auth is enabled but no user. Returns None if auth disabled."""
    if not settings.auth_required:
        return None
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    body: ConversationCreate,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Create a new conversation."""
    owner = _require_user(user)
    return await service.create(
        user_id=owner.id if owner else body.user_id,
        project_id=body.project_id,
        title=body.title,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Get a conversation with all its messages."""
    _require_user(user)
    result = await service.get(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@router.get("/user/{user_id}", response_model=list[ConversationResponse])
async def list_user_conversations(
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """List conversations for a user."""
    _require_user(user)
    return await service.list_by_user(
        user_id=user_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


@router.post("/{conversation_id}/messages", response_model=ConvMessageResponse)
async def add_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Add a message to a conversation."""
    _require_user(user)
    existing = await service.get(conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        return await service.add_message(
            conversation_id=conversation_id,
            role=body.role,
            content=body.content,
            metadata=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Delete a conversation and all its messages."""
    _require_user(user)
    existing = await service.get(conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await service.delete(conversation_id)
    return {"message": "Conversation deleted", "id": str(conversation_id)}
