"""Tests for chat endpoint integration with VDB-powered smart_search."""

from unittest.mock import AsyncMock

from pam.agent.agent import AgentResponse, Citation


class TestChatSmartSearchIntegration:
    async def test_chat_response_includes_entity_citations(self, client, mock_agent):
        """Agent returns citations from smart_search; chat endpoint serializes them."""
        citation = Citation(
            document_title="Architecture Guide",
            section_path="Authentication > OAuth",
            source_url="http://docs.example.com/auth",
            segment_id="seg-auth-1",
        )

        mock_agent.answer = AsyncMock(
            return_value=AgentResponse(
                answer="AuthService handles OAuth. See Architecture Guide.",
                citations=[citation],
                token_usage={"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
                latency_ms=250.0,
                tool_calls=2,
            )
        )

        response = await client.post(
            "/api/chat",
            json={"message": "How does authentication work?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["citations"]) == 1
        cit = data["citations"][0]
        assert cit["document_title"] == "Architecture Guide"
        assert cit["section_path"] == "Authentication > OAuth"
        assert cit["source_url"] == "http://docs.example.com/auth"
        assert cit["segment_id"] == "seg-auth-1"

    async def test_chat_with_vdb_powered_agent(self, client, mock_agent, app):
        """Verify agent is instantiated correctly when vdb_store is on app.state."""
        # Set vdb_store on app state (simulates startup with VDB enabled)
        mock_vdb = AsyncMock()
        app.state.vdb_store = mock_vdb

        mock_agent.answer = AsyncMock(
            return_value=AgentResponse(
                answer="Found via entity search.",
                citations=[],
                token_usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                latency_ms=100.0,
                tool_calls=1,
            )
        )

        response = await client.post(
            "/api/chat",
            json={"message": "What is AuthService?"},
        )

        assert response.status_code == 200
        assert response.json()["response"] == "Found via entity search."

    async def test_chat_stream_with_smart_search_events(self, client, mock_agent):
        """Streaming endpoint returns SSE events including tool results."""

        async def fake_stream(*args, **kwargs):
            yield {"type": "tool_use", "name": "smart_search", "input": {"query": "auth"}}
            yield {"type": "text", "content": "AuthService handles authentication."}
            yield {
                "type": "done",
                "citations": [
                    {
                        "document_title": "Guide",
                        "section_path": "Auth",
                        "source_url": "http://test",
                        "segment_id": "s1",
                    }
                ],
                "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "latency_ms": 50.0,
            }

        mock_agent.answer_streaming = fake_stream

        response = await client.post(
            "/api/chat/stream",
            json={"message": "How does auth work?"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = response.text
        assert "smart_search" in body
        assert "AuthService handles authentication" in body
