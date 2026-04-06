"""Shared fixtures for glossary tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.glossary.store import GlossaryStore


@pytest.fixture
def mock_es_client() -> AsyncMock:
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    client.options = MagicMock(return_value=AsyncMock())
    return client


@pytest.fixture
def glossary_store(mock_es_client: AsyncMock) -> GlossaryStore:
    """Create a GlossaryStore with mocked ES client."""
    return GlossaryStore(
        client=mock_es_client,
        index_name="test_glossary",
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
    """Create a mock GlossaryStore."""
    store = AsyncMock(spec=GlossaryStore)
    store.find_duplicates = AsyncMock(return_value=[])
    store.index_term = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.search_by_alias = AsyncMock(return_value=[])
    store.delete = AsyncMock()
    return store


@pytest.fixture
def mock_session_factory() -> MagicMock:
    """Create a mock async session factory."""
    factory = MagicMock()
    session = AsyncMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory
