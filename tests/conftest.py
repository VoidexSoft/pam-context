"""Shared test fixtures for the PAM Context test suite."""

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.models import KnowledgeSegment, RawDocument


@pytest.fixture
def mock_db_session():
    """Mock async SQLAlchemy session."""
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_es_client():
    """Mock async Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    client.search = AsyncMock(return_value={"hits": {"hits": []}})
    client.bulk = AsyncMock(return_value={"errors": False, "items": []})
    client.delete_by_query = AsyncMock(return_value={"deleted": 0})
    return client


@pytest.fixture
def mock_openai_client():
    """Mock async OpenAI client."""
    client = AsyncMock()
    embedding_data = Mock()
    embedding_data.embedding = [0.1] * 1536
    usage = Mock()
    usage.total_tokens = 10
    response = Mock()
    response.data = [embedding_data]
    response.usage = usage
    client.embeddings = AsyncMock()
    client.embeddings.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def mock_anthropic_client():
    """Mock async Anthropic client."""
    client = AsyncMock()
    text_block = Mock()
    text_block.type = "text"
    text_block.text = "This is the answer."
    response = Mock()
    response.content = [text_block]
    response.stop_reason = "end_turn"
    response.usage = Mock(input_tokens=100, output_tokens=50)
    client.messages = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def sample_knowledge_segment():
    """A sample KnowledgeSegment for testing."""
    return KnowledgeSegment(
        id=uuid.uuid4(),
        content="The quarterly revenue was $10M.",
        content_hash="abc123def456",
        embedding=[0.1] * 1536,
        source_type="markdown",
        source_id="/docs/report.md",
        source_url="file:///docs/report.md",
        section_path="Financial Results > Q1",
        segment_type="text",
        position=0,
        document_title="Q1 Report",
        document_id=uuid.uuid4(),
    )


@pytest.fixture
def sample_raw_document():
    """A sample RawDocument for testing."""
    return RawDocument(
        content=b"# Hello World\n\nThis is a test document.",
        content_type="text/markdown",
        source_id="/tmp/test.md",
        title="test",
        source_url="file:///tmp/test.md",
    )


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory with sample markdown files."""
    (tmp_path / "doc1.md").write_text("# Doc 1\n\nContent of doc 1.")
    (tmp_path / "doc2.md").write_text("# Doc 2\n\nContent of doc 2.")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "doc3.md").write_text("# Doc 3\n\nNested content.")
    (tmp_path / "not_markdown.txt").write_text("Not a markdown file.")
    return tmp_path
