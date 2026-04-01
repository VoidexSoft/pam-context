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
