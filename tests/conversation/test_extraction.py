"""Tests for FactExtractionPipeline."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.conversation.extraction import FactExtractionPipeline


@pytest.fixture
def mock_memory_service():
    svc = AsyncMock()
    svc.store = AsyncMock()
    return svc


@pytest.fixture
def extraction_pipeline(mock_memory_service):
    return FactExtractionPipeline(
        memory_service=mock_memory_service,
        anthropic_api_key="test-key",
        model="claude-haiku-4-5-20251001",
    )


@pytest.mark.asyncio
async def test_extract_facts_from_exchange(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() calls LLM and stores extracted facts."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = '[{"type": "fact", "content": "User prefers Python over JS"}]'
    llm_response.content = [text_block]

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="I always prefer Python for backend work",
            assistant_response="Got it, I'll keep that in mind.",
            user_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )

    assert len(results) == 1
    assert results[0]["type"] == "fact"
    mock_memory_service.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_no_facts(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() returns empty list when no facts found."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "[]"
    llm_response.content = [text_block]

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="What time is it?",
            assistant_response="I don't have access to the current time.",
        )

    assert results == []
    mock_memory_service.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_handles_llm_error(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() returns empty list on LLM failure."""
    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

        results = await extraction_pipeline.extract_from_exchange(
            user_message="Hello",
            assistant_response="Hi there!",
        )

    assert results == []
    mock_memory_service.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_handles_malformed_json(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() returns empty list on malformed LLM output."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "not valid json"
    llm_response.content = [text_block]

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="Hello",
            assistant_response="Hi!",
        )

    assert results == []


@pytest.mark.asyncio
async def test_extract_multiple_facts(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() stores multiple extracted facts."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = (
        '['
        '{"type": "fact", "content": "Team uses PostgreSQL for analytics"},'
        '{"type": "preference", "content": "User prefers concise answers"}'
        ']'
    )
    llm_response.content = [text_block]

    mock_memory_service.store.return_value = MagicMock()

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="We use PostgreSQL. Please keep answers short.",
            assistant_response="Understood. Noted your preferences.",
            user_id=uuid.uuid4(),
        )

    assert len(results) == 2
    assert mock_memory_service.store.await_count == 2
