"""Shared fixtures for memory tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.memory.service import MemoryService
from pam.memory.store import MemoryStore


@pytest.fixture
def mock_es_client() -> AsyncMock:
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    # options() is sync and returns a client-like object with async methods
    client.options = MagicMock(return_value=AsyncMock())
    return client


@pytest.fixture
def memory_store(mock_es_client: AsyncMock) -> MemoryStore:
    """Create a MemoryStore with mocked ES client."""
    return MemoryStore(
        client=mock_es_client,
        index_name="test_memories",
        embedding_dims=1536,
    )


@pytest.fixture
def mock_embedder() -> AsyncMock:
    """Create a mock embedder."""
    embedder = AsyncMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return embedder


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock MemoryStore."""
    store = AsyncMock(spec=MemoryStore)
    store.find_duplicates = AsyncMock(return_value=[])
    store.index_memory = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.delete = AsyncMock()
    store.update_importance = AsyncMock()
    return store


@pytest.fixture
def mock_session_factory() -> MagicMock:
    """Create a mock async session factory."""
    factory = MagicMock()
    session = AsyncMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.fixture
def memory_service(mock_session_factory, mock_store, mock_embedder) -> MemoryService:
    """Create a MemoryService with all dependencies mocked."""
    return MemoryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
        anthropic_api_key="test-key",
        dedup_threshold=0.9,
        merge_model="claude-haiku-4-5-20251001",
    )
