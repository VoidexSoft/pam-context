"""Conversation endpoints — CRUD for conversations and messages."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from pam.api.auth import get_current_user
from pam.api.rate_limit import limiter
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
@limiter.limit(settings.rate_limit_conversation)
async def create_conversation(
    request: Request,
    body: ConversationCreate,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Create a new conversation."""
    owner = _require_user(user)
    # When auth is disabled, require user_id in the request body
    effective_user_id = owner.id if owner else body.user_id
    return await service.create(
        user_id=effective_user_id,
        project_id=body.project_id,
        title=body.title,
    )


# NOTE: /user/{user_id} must be registered BEFORE /{conversation_id}
# to prevent FastAPI from matching "user" as a conversation_id UUID.
@router.get("/user/{user_id}", response_model=list[ConversationResponse])
@limiter.limit(settings.rate_limit_conversation)
async def list_user_conversations(
    request: Request,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """List conversations for a user."""
    owner = _require_user(user)
    # When auth is enabled, only allow listing your own conversations
    effective_user_id = owner.id if owner else user_id
    return await service.list_by_user(
        user_id=effective_user_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
@limiter.limit(settings.rate_limit_conversation)
async def get_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Get a conversation with all its messages."""
    owner = _require_user(user)
    result = await service.get(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if owner and result.user_id and result.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return result


@router.post("/{conversation_id}/messages", response_model=ConvMessageResponse)
@limiter.limit(settings.rate_limit_conversation)
async def add_message(
    request: Request,
    conversation_id: uuid.UUID,
    body: MessageCreate,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Add a message to a conversation."""
    owner = _require_user(user)
    existing = await service.get(conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if owner and existing.user_id and existing.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Access denied")
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
@limiter.limit(settings.rate_limit_conversation)
async def delete_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Delete a conversation and all its messages."""
    owner = _require_user(user)
    existing = await service.get(conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if owner and existing.user_id and existing.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Access denied")
    await service.delete(conversation_id)
    return {"message": "Conversation deleted", "id": str(conversation_id)}
