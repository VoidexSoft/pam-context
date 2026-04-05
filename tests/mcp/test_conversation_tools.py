"""Tests for conversation MCP tools."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_save_conversation(mock_services):
    """pam_save_conversation stores messages in a conversation."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=UTC)

    mock_services.conversation_service.create.return_value = MagicMock(id=conv_id, title="Test Chat")
    mock_services.conversation_service.add_message.return_value = MagicMock(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role="user",
        content="Hello",
        created_at=now,
    )

    result = await mcp_server._pam_save_conversation(
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        title="Test Chat",
    )

    parsed = json.loads(result)
    assert "conversation_id" in parsed
    assert parsed["messages_saved"] == 2
    assert mock_services.conversation_service.add_message.await_count == 2


@pytest.mark.asyncio
async def test_pam_get_conversation_context(mock_services):
    """pam_get_conversation_context returns recent conversation context."""
    conv_id = uuid.uuid4()
    mock_services.conversation_service.get_recent_context.return_value = (
        "user: What is PAM?\nassistant: PAM is a knowledge base."
    )

    result = await mcp_server._pam_get_conversation_context(
        conversation_id=str(conv_id),
    )

    assert "PAM" in result
    mock_services.conversation_service.get_recent_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_save_conversation_service_unavailable(mock_services):
    """pam_save_conversation returns error when service is None."""
    mock_services.conversation_service = None

    result = await mcp_server._pam_save_conversation(
        messages=[{"role": "user", "content": "Hello"}],
    )
    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_pam_get_conversation_context_service_unavailable(mock_services):
    """pam_get_conversation_context returns error when service is None."""
    mock_services.conversation_service = None

    result = await mcp_server._pam_get_conversation_context(
        conversation_id=str(uuid.uuid4()),
    )
    parsed = json.loads(result)
    assert "error" in parsed
