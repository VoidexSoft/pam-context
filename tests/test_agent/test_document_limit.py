"""Tests for document content size limiting in agent tools."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from pam.agent.agent import RetrievalAgent

MAX_DOC_CHARS = 50_000  # ~12,500 tokens at 4 chars/token


def _make_agent(db_session: AsyncMock) -> RetrievalAgent:
    return RetrievalAgent(
        search_service=MagicMock(),
        embedder=MagicMock(),
        api_key="test",
        model="test",
        db_session=db_session,
    )


def _make_doc(segment_count: int, segment_size: int = 2000) -> Mock:
    """Create a mock Document with segments."""
    doc = Mock()
    doc.title = "Big Document"
    doc.source_id = "big.md"
    doc.source_url = "file:///big.md"
    doc.segments = [Mock(content="x" * segment_size, position=i) for i in range(segment_count)]
    return doc


@pytest.mark.asyncio
async def test_large_document_truncated():
    """Documents exceeding MAX_DOC_CHARS are truncated with a notice."""
    db = AsyncMock()
    # 100 segments * 2000 chars = 200,000 chars (well over limit)
    doc = _make_doc(segment_count=100, segment_size=2000)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = doc
    db.execute = AsyncMock(return_value=result_mock)

    agent = _make_agent(db)
    result_text, _citations = await agent._get_document_context({"document_title": "Big Document"})

    assert len(result_text) <= MAX_DOC_CHARS + 500  # header + truncation notice
    assert "[truncated]" in result_text


@pytest.mark.asyncio
async def test_small_document_not_truncated():
    """Small documents pass through without truncation."""
    db = AsyncMock()
    doc = _make_doc(segment_count=3, segment_size=100)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = doc
    db.execute = AsyncMock(return_value=result_mock)

    agent = _make_agent(db)
    result_text, _citations = await agent._get_document_context({"document_title": "Small Document"})

    assert "[truncated]" not in result_text
