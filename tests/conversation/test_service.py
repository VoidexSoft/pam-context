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
