"""Tests for Memory model and schemas."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.common.models import Memory
from pam.memory.service import MemoryService


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


@pytest.mark.asyncio
async def test_store_memory_no_duplicate(memory_service, mock_store, mock_embedder):
    """store() inserts a new memory when no duplicate exists."""
    mock_store.find_duplicates.return_value = []

    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.store(
        content="Revenue target is $10M",
        memory_type="fact",
        source="manual",
        user_id=None,
        project_id=None,
    )

    assert result is not None
    assert result.content == "Revenue target is $10M"
    assert result.type == "fact"
    mock_embedder.embed_texts.assert_awaited_once_with(["Revenue target is $10M"])
    mock_store.find_duplicates.assert_awaited_once()
    mock_store.index_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_memory_with_duplicate_merges(memory_service, mock_store, mock_embedder):
    """store() merges content when a duplicate is found (cosine > threshold)."""
    dup_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_store.find_duplicates.return_value = [
        {"memory_id": dup_id, "score": 0.95, "content": "Revenue target is $10M"},
    ]

    mock_session = AsyncMock()
    mock_existing = MagicMock()
    mock_existing.id = uuid.UUID(dup_id)
    mock_existing.content = "Revenue target is $10M"
    mock_existing.type = "fact"
    mock_existing.source = "manual"
    mock_existing.metadata_ = {}
    mock_existing.importance = 0.5
    mock_existing.access_count = 0
    mock_existing.last_accessed_at = None
    mock_existing.expires_at = None
    mock_existing.user_id = None
    mock_existing.project_id = None
    mock_existing.created_at = datetime.now(tz=timezone.utc)
    mock_existing.updated_at = datetime.now(tz=timezone.utc)

    mock_get_result = MagicMock()
    mock_get_result.scalars.return_value.first.return_value = mock_existing
    mock_session.execute = AsyncMock(return_value=mock_get_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    # Mock the LLM merge
    with patch.object(memory_service, "_merge_contents", new_callable=AsyncMock) as mock_merge:
        mock_merge.return_value = "Revenue target is $10M for Q1 2026"

        result = await memory_service.store(
            content="Q1 2026 revenue target is $10M",
            memory_type="fact",
            user_id=None,
        )

    assert result is not None
    mock_merge.assert_awaited_once()
    mock_store.index_memory.assert_awaited_once()
