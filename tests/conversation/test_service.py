"""Tests for Conversation and Message models."""

import uuid
from datetime import datetime, timezone

from pam.common.models import Conversation, Message


def test_conversation_model_has_required_fields():
    """Conversation ORM model has all expected columns."""
    columns = {c.name for c in Conversation.__table__.columns}
    expected = {
        "id", "user_id", "project_id", "title",
        "started_at", "last_active",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


def test_message_model_has_required_fields():
    """Message ORM model has all expected columns."""
    columns = {c.name for c in Message.__table__.columns}
    expected = {
        "id", "conversation_id", "role", "content",
        "metadata", "created_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


def test_message_role_constraint():
    """Message role column has a check constraint."""
    constraints = [c.name for c in Message.__table__.constraints if hasattr(c, "name") and c.name]
    assert "ck_messages_role" in constraints


from pam.common.models import (
    ConversationCreate,
    ConversationResponse,
    ConversationDetail,
    MessageCreate,
    ConvMessageResponse,
)


def test_conversation_create_schema():
    """ConversationCreate accepts optional user_id, project_id, title."""
    c = ConversationCreate(title="Test Chat")
    assert c.title == "Test Chat"
    assert c.user_id is None
    assert c.project_id is None


def test_conversation_create_minimal():
    """ConversationCreate works with no arguments."""
    c = ConversationCreate()
    assert c.title is None


def test_message_create_schema():
    """MessageCreate requires role and content."""
    m = MessageCreate(role="user", content="Hello")
    assert m.role == "user"
    assert m.content == "Hello"
    assert m.metadata == {}


def test_conversation_response_schema():
    """ConversationResponse has all expected fields."""
    now = datetime.now(tz=timezone.utc)
    cr = ConversationResponse(
        id=uuid.uuid4(),
        user_id=None,
        project_id=None,
        title="Chat",
        started_at=now,
        last_active=now,
        message_count=5,
    )
    assert cr.message_count == 5


def test_conversation_detail_includes_messages():
    """ConversationDetail extends ConversationResponse with messages list."""
    now = datetime.now(tz=timezone.utc)
    msg = ConvMessageResponse(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role="user",
        content="Hi",
        metadata={},
        created_at=now,
    )
    detail = ConversationDetail(
        id=uuid.uuid4(),
        user_id=None,
        project_id=None,
        title="Chat",
        started_at=now,
        last_active=now,
        message_count=1,
        messages=[msg],
    )
    assert len(detail.messages) == 1


import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pam.conversation.service import ConversationService


@pytest.mark.asyncio
async def test_create_conversation(conversation_service, mock_session):
    """create() inserts a Conversation row and returns ConversationResponse."""
    user_id = uuid.uuid4()
    result = await conversation_service.create(user_id=user_id, title="Test Chat")

    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()
    assert result.title == "Test Chat"
    assert result.user_id == user_id
    assert result.message_count == 0


@pytest.mark.asyncio
async def test_create_with_id(conversation_service, mock_session):
    """create_with_id() uses the supplied UUID instead of generating one."""
    conv_id = uuid.uuid4()
    result = await conversation_service.create_with_id(
        conversation_id=conv_id, title="Chat with known ID"
    )

    mock_session.add.assert_called_once()
    # The Conversation passed to session.add should have our ID
    added_conv = mock_session.add.call_args[0][0]
    assert added_conv.id == conv_id
    assert result.title == "Chat with known ID"


@pytest.mark.asyncio
async def test_get_conversation_found(conversation_service, mock_session):
    """get() returns ConversationDetail when conversation exists."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    mock_conv = MagicMock()
    mock_conv.id = conv_id
    mock_conv.user_id = None
    mock_conv.project_id = None
    mock_conv.title = "Chat"
    mock_conv.started_at = now
    mock_conv.last_active = now
    mock_conv.messages = []

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_session.execute.return_value = mock_result

    result = await conversation_service.get(conv_id)
    assert result is not None
    assert result.id == conv_id
    assert result.messages == []


@pytest.mark.asyncio
async def test_get_conversation_not_found(conversation_service, mock_session):
    """get() returns None when conversation doesn't exist."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await conversation_service.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_delete_conversation(conversation_service, mock_session):
    """delete() removes conversation and returns True."""
    conv_id = uuid.uuid4()

    mock_conv = MagicMock()
    mock_conv.id = conv_id
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_session.execute.return_value = mock_result

    result = await conversation_service.delete(conv_id)
    assert result is True
    mock_session.delete.assert_awaited_once_with(mock_conv)


@pytest.mark.asyncio
async def test_delete_conversation_not_found(conversation_service, mock_session):
    """delete() returns False when conversation doesn't exist."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await conversation_service.delete(uuid.uuid4())
    assert result is False
