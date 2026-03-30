"""Shared fixtures for memory tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.memory.store import MemoryStore


@pytest.fixture()
def mock_es_client() -> AsyncMock:
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    return client


@pytest.fixture()
def memory_store(mock_es_client: AsyncMock) -> MemoryStore:
    """Create a MemoryStore with mocked ES client."""
    return MemoryStore(
        client=mock_es_client,
        index_name="test_memories",
        embedding_dims=1536,
    )
