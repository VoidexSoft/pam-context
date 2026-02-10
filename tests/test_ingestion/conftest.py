"""Ingestion-specific test fixtures."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from pam.ingestion.connectors.base import BaseConnector
from pam.ingestion.embedders.base import BaseEmbedder
from pam.ingestion.parsers.docling_parser import DoclingParser
from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore
from pam.ingestion.stores.postgres_store import PostgresStore


@pytest.fixture
def mock_connector():
    """Mock document connector."""
    connector = AsyncMock(spec=BaseConnector)
    connector.list_documents = AsyncMock(return_value=[])
    connector.fetch_document = AsyncMock()
    connector.get_content_hash = AsyncMock(return_value="newhash123")
    return connector


@pytest.fixture
def mock_parser():
    """Mock Docling parser."""
    parser = MagicMock(spec=DoclingParser)
    parser.parse = MagicMock(return_value=Mock())
    return parser


@pytest.fixture
def mock_embedder():
    """Mock embedder."""
    embedder = AsyncMock(spec=BaseEmbedder)
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    embedder.embed_texts_with_cache = AsyncMock(return_value=[[0.1] * 1536])
    embedder.dimensions = 1536
    embedder.model_name = "text-embedding-3-large"
    return embedder


@pytest.fixture
def mock_pg_store():
    """Mock PostgresStore."""
    store = AsyncMock(spec=PostgresStore)
    store.get_document_by_source = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_es_store():
    """Mock ElasticsearchStore."""
    store = AsyncMock(spec=ElasticsearchStore)
    store.ensure_index = AsyncMock()
    store.bulk_index = AsyncMock(return_value=0)
    store.delete_by_document = AsyncMock(return_value=0)
    return store
