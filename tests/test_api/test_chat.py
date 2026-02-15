"""Tests for POST /api/chat endpoint."""

from unittest.mock import AsyncMock, Mock

from pam.agent.agent import AgentResponse


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
        response = await client.post(
            "/api/chat",
            json={"message": "test"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "An internal error occurred"

    async def test_chat_with_conversation_history(self, client, mock_agent):
        """Conversation history is forwarded to the agent as a kwarg."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        response = await client.post(
            "/api/chat",
            json={
                "message": "Follow up question",
                "conversation_history": history,
            },
        )
        assert response.status_code == 200
        mock_agent.answer.assert_called_once()
        call_args = mock_agent.answer.call_args
        assert call_args[0][0] == "Follow up question"
        assert call_args[1]["conversation_history"] == history

    async def test_chat_with_source_type_filter(self, client, mock_agent):
        """Source type filter is forwarded to the agent as a kwarg."""
        response = await client.post(
            "/api/chat",
            json={
                "message": "What is revenue?",
                "source_type": "confluence",
            },
        )
        assert response.status_code == 200
        call_args = mock_agent.answer.call_args
        assert call_args[1]["source_type"] == "confluence"

    async def test_chat_response_includes_citations(self, client, mock_agent):
        """Citations from the agent response are serialised into the JSON body."""
        citation = Mock()
        citation.document_title = "Report"
        citation.section_path = "Section 1"
        citation.source_url = "http://example.com"
        citation.segment_id = "seg-123"

        mock_agent.answer = AsyncMock(
            return_value=AgentResponse(
                answer="Answer with citation",
                citations=[citation],
                token_usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                latency_ms=100.0,
                tool_calls=1,
            )
        )

        response = await client.post(
            "/api/chat",
            json={"message": "Tell me about revenue"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "Answer with citation"
        assert len(data["citations"]) == 1

        cit = data["citations"][0]
        assert cit["document_title"] == "Report"
        assert cit["section_path"] == "Section 1"
        assert cit["source_url"] == "http://example.com"
        assert cit["segment_id"] == "seg-123"

    async def test_chat_stream_endpoint_exists(self, client, mock_agent):
        """POST /api/chat/stream returns 200 with a streaming response."""

        async def fake_stream(*args, **kwargs):
            yield {"type": "text", "content": "streamed answer"}

        mock_agent.answer_streaming = fake_stream

        response = await client.post(
            "/api/chat/stream",
            json={"message": "stream this"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        # Verify the SSE payload contains our chunk
        body = response.text
        assert "streamed answer" in body
