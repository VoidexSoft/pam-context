"""Tests for Memory model and schemas."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.common.models import Memory, MemoryCreate, MemoryResponse


def test_memory_model_has_required_fields():
    """Memory ORM model has all expected columns."""
    columns = {c.name for c in Memory.__table__.columns}
    expected = {
        "id", "user_id", "project_id", "type", "content", "source",
        "metadata", "importance", "access_count", "last_accessed_at",
        "expires_at", "created_at", "updated_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


def test_memory_create_schema_defaults():
    """MemoryCreate has correct defaults."""
    mc = MemoryCreate(content="User prefers Python")
    assert mc.type == "fact"
    assert mc.importance == 0.5
    assert mc.metadata == {}
    assert mc.source is None


def test_memory_create_schema_validation():
    """MemoryCreate rejects invalid importance values."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryCreate(content="test", importance=1.5)

    with pytest.raises(ValidationError):
        MemoryCreate(content="test", importance=-0.1)


def test_memory_create_rejects_empty_content():
    """MemoryCreate rejects empty content at schema level."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryCreate(content="")


def test_memory_create_rejects_oversized_content():
    """MemoryCreate rejects content exceeding 10k chars at schema level."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryCreate(content="x" * 10_001)


def test_memory_response_from_attributes():
    """MemoryResponse can be constructed from ORM-like attributes."""
    now = datetime.now(tz=UTC)
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
    mock_existing.created_at = datetime.now(tz=UTC)
    mock_existing.updated_at = datetime.now(tz=UTC)

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


@pytest.mark.asyncio
async def test_merge_uses_max_importance(memory_service, mock_store, mock_embedder):
    """_merge_and_update uses max(existing, new) for importance."""
    dup_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_store.find_duplicates.return_value = [
        {"memory_id": dup_id, "score": 0.95, "content": "Important fact"},
    ]

    mock_session = AsyncMock()
    mock_existing = MagicMock()
    mock_existing.id = uuid.UUID(dup_id)
    mock_existing.content = "Important fact"
    mock_existing.type = "fact"
    mock_existing.source = "manual"
    mock_existing.metadata_ = {}
    mock_existing.importance = 0.9  # Existing has high importance
    mock_existing.access_count = 0
    mock_existing.last_accessed_at = None
    mock_existing.expires_at = None
    mock_existing.user_id = None
    mock_existing.project_id = None
    mock_existing.created_at = datetime.now(tz=UTC)
    mock_existing.updated_at = datetime.now(tz=UTC)

    mock_get_result = MagicMock()
    mock_get_result.scalars.return_value.first.return_value = mock_existing
    mock_session.execute = AsyncMock(return_value=mock_get_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    with patch.object(memory_service, "_merge_contents", new_callable=AsyncMock) as mock_merge:
        mock_merge.return_value = "Merged important fact"

        await memory_service.store(
            content="Less important version",
            memory_type="fact",
            importance=0.3,  # Lower importance should not downgrade
            user_id=None,
        )

    # Should keep 0.9 (max of 0.9, 0.3), not downgrade to 0.3
    assert mock_existing.importance == 0.9


@pytest.mark.asyncio
async def test_search_memories(memory_service, mock_store, mock_embedder):
    """search() embeds query and returns scored memories from ES (no access_count bump)."""
    memory_id = uuid.uuid4()
    mock_store.search.return_value = [
        {"memory_id": str(memory_id), "score": 0.92, "content": "Revenue is $10M", "type": "fact", "importance": 0.7},
    ]

    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Revenue is $10M"
    mock_memory.type = "fact"
    mock_memory.importance = 0.7
    mock_memory.access_count = 2
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = "manual"
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=UTC)
    mock_memory.updated_at = datetime.now(tz=UTC)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_memory]
    mock_session.execute = AsyncMock(return_value=mock_result)
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    results = await memory_service.search(query="revenue target", top_k=5)

    assert len(results) == 1
    assert results[0].memory.content == "Revenue is $10M"
    assert results[0].score == 0.92
    mock_embedder.embed_texts.assert_awaited_once_with(["revenue target"])
    mock_store.search.assert_awaited_once()
    # search() should NOT bump access_count
    mock_session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_memory_by_id(memory_service):
    """get() fetches a single memory by ID and bumps access count."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Test fact"
    mock_memory.type = "fact"
    mock_memory.importance = 0.5
    mock_memory.access_count = 0
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = None
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=UTC)
    mock_memory.updated_at = datetime.now(tz=UTC)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.get(memory_id)
    assert result is not None
    assert result.content == "Test fact"
    # get() should bump access_count
    assert mock_memory.access_count == 1
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_memory_not_found(memory_service):
    """get() returns None when memory doesn't exist."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_delete_memory(memory_service, mock_store):
    """delete() removes memory from PG and ES."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    deleted = await memory_service.delete(memory_id)
    assert deleted is True
    mock_session.delete.assert_awaited_once_with(mock_memory)
    mock_store.delete.assert_awaited_once_with(memory_id)


@pytest.mark.asyncio
async def test_delete_memory_not_found(memory_service, mock_store):
    """delete() returns False when memory doesn't exist."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    deleted = await memory_service.delete(uuid.uuid4())
    assert deleted is False
    mock_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_memory(memory_service, mock_store, mock_embedder):
    """update() modifies content and re-indexes in ES."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Old fact"
    mock_memory.type = "fact"
    mock_memory.importance = 0.5
    mock_memory.access_count = 0
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = None
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=UTC)
    mock_memory.updated_at = datetime.now(tz=UTC)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.update(
        memory_id=memory_id,
        content="Updated fact",
        importance=0.8,
    )
    assert result is not None
    mock_embedder.embed_texts.assert_awaited_once_with(["Updated fact"])
    mock_store.index_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_importance_only(memory_service, mock_store, mock_embedder):
    """update() with importance-only change calls update_importance on ES."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Some fact"
    mock_memory.type = "fact"
    mock_memory.importance = 0.5
    mock_memory.access_count = 0
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = None
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=UTC)
    mock_memory.updated_at = datetime.now(tz=UTC)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.update(memory_id=memory_id, importance=0.9)
    assert result is not None
    mock_store.update_importance.assert_awaited_once_with(memory_id, 0.9)
    mock_store.index_memory.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_clear_expires_at(memory_service, mock_store):
    """update() with clear_expires_at=True sets expires_at to None."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Expiring fact"
    mock_memory.type = "fact"
    mock_memory.importance = 0.5
    mock_memory.access_count = 0
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = None
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = datetime.now(tz=UTC)
    mock_memory.created_at = datetime.now(tz=UTC)
    mock_memory.updated_at = datetime.now(tz=UTC)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    await memory_service.update(memory_id=memory_id, clear_expires_at=True)
    assert mock_memory.expires_at is None


@pytest.mark.asyncio
async def test_store_rejects_empty_content(memory_service):
    """store() raises ValueError for empty content."""
    with pytest.raises(ValueError, match="empty"):
        await memory_service.store(content="", memory_type="fact")

    with pytest.raises(ValueError, match="empty"):
        await memory_service.store(content="   ", memory_type="fact")


@pytest.mark.asyncio
async def test_store_rejects_oversized_content(memory_service):
    """store() raises ValueError for content exceeding 10k chars."""
    with pytest.raises(ValueError, match="10,000"):
        await memory_service.store(content="x" * 10_001, memory_type="fact")


@pytest.mark.asyncio
async def test_merge_contents_fallback(memory_service):
    """_merge_contents falls back to new content when LLM call fails."""
    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            side_effect=RuntimeError("API unavailable")
        )

        result = await memory_service._merge_contents("old fact", "new fact")
        assert result == "new fact"
