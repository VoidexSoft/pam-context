"""Tests for POST /api/chat endpoint."""

from unittest.mock import AsyncMock

import pytest


class TestChatEndpoint:
    async def test_chat_success(self, client, mock_agent):
        response = await client.post(
            "/api/chat",
            json={"message": "What is revenue?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "Test answer"
        assert data["citations"] == []
        assert data["token_usage"]["total_tokens"] == 15
        mock_agent.answer.assert_called_once_with("What is revenue?")

    async def test_chat_with_conversation_id(self, client, mock_agent):
        response = await client.post(
            "/api/chat",
            json={"message": "Follow up", "conversation_id": "conv-123"},
        )
        assert response.status_code == 200
        assert response.json()["conversation_id"] == "conv-123"

    async def test_chat_validation_error(self, client):
        response = await client.post("/api/chat", json={})
        assert response.status_code == 422

    async def test_chat_agent_error(self, client, mock_agent):
        mock_agent.answer = AsyncMock(side_effect=RuntimeError("Agent failed"))
        with pytest.raises(RuntimeError, match="Agent failed"):
            await client.post(
                "/api/chat",
                json={"message": "test"},
            )
