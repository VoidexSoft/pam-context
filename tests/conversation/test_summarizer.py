"""Tests for ConversationSummarizer."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.conversation.summarizer import ConversationSummarizer


@pytest.fixture
def mock_memory_service():
    svc = AsyncMock()
    svc.store = AsyncMock()
    return svc


@pytest.fixture
def mock_conversation_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def summarizer(mock_conversation_service, mock_memory_service):
    return ConversationSummarizer(
        conversation_service=mock_conversation_service,
        memory_service=mock_memory_service,
        anthropic_api_key="test-key",
        model="claude-haiku-4-5-20251001",
        summary_threshold=5,
    )


@pytest.mark.asyncio
async def test_should_summarize_true(summarizer, mock_conversation_service):
    """should_summarize() returns True when message count exceeds threshold."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    detail = MagicMock()
    detail.message_count = 10
    mock_conversation_service.get.return_value = detail

    result = await summarizer.should_summarize(conv_id)
    assert result is True


@pytest.mark.asyncio
async def test_should_summarize_false(summarizer, mock_conversation_service):
    """should_summarize() returns False when message count is below threshold."""
    conv_id = uuid.uuid4()
    detail = MagicMock()
    detail.message_count = 3
    mock_conversation_service.get.return_value = detail

    result = await summarizer.should_summarize(conv_id)
    assert result is False


@pytest.mark.asyncio
async def test_should_summarize_not_found(summarizer, mock_conversation_service):
    """should_summarize() returns False when conversation not found."""
    mock_conversation_service.get.return_value = None
    result = await summarizer.should_summarize(uuid.uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_summarize_creates_memory(summarizer, mock_conversation_service, mock_memory_service):
    """summarize() generates summary and stores as conversation_summary memory."""
    conv_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    msg1 = MagicMock()
    msg1.role = "user"
    msg1.content = "Tell me about our Q1 targets"
    msg2 = MagicMock()
    msg2.role = "assistant"
    msg2.content = "The Q1 revenue target is $10M across all regions."

    detail = MagicMock()
    detail.messages = [msg1, msg2]
    detail.user_id = user_id
    detail.project_id = None
    detail.id = conv_id
    detail.message_count = 6
    mock_conversation_service.get.return_value = detail

    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "Discussion about Q1 revenue targets: $10M across all regions."
    llm_response.content = [text_block]

    with patch.object(summarizer, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        summary = await summarizer.summarize(conv_id)

    assert "Q1" in summary
    mock_memory_service.store.assert_awaited_once()
    call_kwargs = mock_memory_service.store.call_args.kwargs
    assert call_kwargs["memory_type"] == "conversation_summary"
    assert call_kwargs["user_id"] == user_id


@pytest.mark.asyncio
async def test_summarize_not_found(summarizer, mock_conversation_service):
    """summarize() returns empty string when conversation not found."""
    mock_conversation_service.get.return_value = None
    result = await summarizer.summarize(uuid.uuid4())
    assert result == ""


@pytest.mark.asyncio
async def test_summarize_handles_llm_error(summarizer, mock_conversation_service, mock_memory_service):
    """summarize() returns empty string on LLM failure."""
    detail = MagicMock()
    detail.messages = [MagicMock(role="user", content="Hello")]
    detail.user_id = None
    detail.project_id = None
    detail.id = uuid.uuid4()
    detail.message_count = 6
    mock_conversation_service.get.return_value = detail

    with patch.object(summarizer, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
        result = await summarizer.summarize(detail.id)

    assert result == ""
    mock_memory_service.store.assert_not_awaited()
