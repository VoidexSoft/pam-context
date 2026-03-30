"""Tests for Memory model and schemas."""

import uuid
from datetime import datetime, timezone

from pam.common.models import Memory


def test_memory_model_has_required_fields():
    """Memory ORM model has all expected columns."""
    columns = {c.name for c in Memory.__table__.columns}
    expected = {
        "id", "user_id", "project_id", "type", "content", "source",
        "metadata", "importance", "access_count", "last_accessed_at",
        "expires_at", "created_at", "updated_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


from pam.common.models import MemoryCreate, MemoryResponse, MemoryUpdate, MemorySearchQuery


def test_memory_create_schema_defaults():
    """MemoryCreate has correct defaults."""
    mc = MemoryCreate(content="User prefers Python")
    assert mc.type == "fact"
    assert mc.importance == 0.5
    assert mc.metadata == {}
    assert mc.source is None


def test_memory_create_schema_validation():
    """MemoryCreate rejects invalid importance values."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryCreate(content="test", importance=1.5)

    with pytest.raises(ValidationError):
        MemoryCreate(content="test", importance=-0.1)


def test_memory_response_from_attributes():
    """MemoryResponse can be constructed from ORM-like attributes."""
    now = datetime.now(tz=timezone.utc)
    mr = MemoryResponse(
        id=uuid.uuid4(),
        type="fact",
        content="Test memory",
        importance=0.7,
        access_count=3,
        created_at=now,
        updated_at=now,
    )
    assert mr.type == "fact"
    assert mr.importance == 0.7
