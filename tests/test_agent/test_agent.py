"""Tests for RetrievalAgent — tool-use loop with mocked Anthropic + search."""

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pam.agent.agent import RetrievalAgent
from pam.retrieval.types import SearchResult


def _make_text_block(text):
    block = Mock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(name, input_dict, tool_id="tool_1"):
    block = Mock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    block.id = tool_id
    return block


def _make_response(content, stop_reason="end_turn", input_tokens=100, output_tokens=50):
    resp = Mock()
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage = Mock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


class TestRetrievalAgent:
    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_simple_answer(self, mock_anthropic_cls):
        """Agent returns a direct answer without tool use."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_response([_make_text_block("The answer is 42.")]))
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_embedder = AsyncMock()

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result = await agent.answer("What is the answer?")

        assert result.answer == "The answer is 42."
        assert result.tool_calls == 0
        assert result.token_usage["input_tokens"] == 100

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_tool_use_loop(self, mock_anthropic_cls):
        """Agent calls search_knowledge tool, then provides answer."""
        mock_client = AsyncMock()

        # First response: tool_use
        tool_response = _make_response(
            [_make_tool_use_block("search_knowledge", {"query": "revenue"})],
            stop_reason="tool_use",
        )
        # Second response: final answer
        final_response = _make_response(
            [_make_text_block("Revenue was $10M. [Source: Report > Q1](file:///r.md)")],
        )
        mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(
            return_value=[
                SearchResult(
                    segment_id=uuid.uuid4(),
                    content="Revenue was $10M",
                    score=0.9,
                    source_url="file:///r.md",
                    document_title="Report",
                    section_path="Q1",
                )
            ]
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result = await agent.answer("What was the revenue?")

        assert "10M" in result.answer
        assert result.tool_calls == 1
        assert len(result.citations) == 1
        assert result.citations[0].document_title == "Report"

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_max_iterations(self, mock_anthropic_cls):
        """Agent should stop after MAX_TOOL_ITERATIONS."""
        mock_client = AsyncMock()
        # Always return tool_use, never end_turn
        mock_client.messages.create = AsyncMock(
            return_value=_make_response(
                [_make_tool_use_block("search_knowledge", {"query": "x"})],
                stop_reason="tool_use",
            )
        )
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result = await agent.answer("infinite loop?")

        assert "unable to fully answer" in result.answer.lower()
        assert result.tool_calls == 5  # MAX_TOOL_ITERATIONS


class TestExtractText:
    def test_single_text_block(self):
        content = [_make_text_block("Hello")]
        assert RetrievalAgent._extract_text(content) == "Hello"

    def test_multiple_text_blocks(self):
        content = [_make_text_block("Hello"), _make_text_block("World")]
        assert RetrievalAgent._extract_text(content) == "Hello\nWorld"

    def test_mixed_blocks(self):
        text = _make_text_block("Answer")
        tool = Mock(spec=[])  # no text attribute
        content = [text, tool]
        assert RetrievalAgent._extract_text(content) == "Answer"


class TestSearchKnowledge:
    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_no_results(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = AsyncMock()
        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result_text, citations = await agent._search_knowledge({"query": "unknown"})
        assert "No relevant results" in result_text
        assert citations == []

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_formats_results(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = AsyncMock()
        mock_search = AsyncMock()
        mock_search.search = AsyncMock(
            return_value=[
                SearchResult(
                    segment_id=uuid.uuid4(),
                    content="Some knowledge",
                    score=0.9,
                    source_url="file:///doc.md",
                    document_title="Doc",
                    section_path="Section 1",
                ),
            ]
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result_text, citations = await agent._search_knowledge({"query": "knowledge"})
        assert "Some knowledge" in result_text
        assert "Doc > Section 1" in result_text
        assert len(citations) == 1


class TestStreamingDoubleSend:
    """Regression tests for issue #19: streaming double-sends answer after tool use."""

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_no_duplicate_answer_after_tool_use(self, mock_anthropic_cls):
        """After tool use + end_turn, Phase B must NOT fire a second streaming call."""
        mock_client = AsyncMock()

        # First response: tool_use
        tool_response = _make_response(
            [_make_tool_use_block("search_knowledge", {"query": "revenue"})],
            stop_reason="tool_use",
        )
        # Second response: end_turn with the final answer
        final_response = _make_response(
            [_make_text_block("Revenue was $10M.")],
            stop_reason="end_turn",
        )
        mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
        # Phase B would call messages.stream — should NOT be called
        mock_client.messages.stream = Mock()
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(
            return_value=[
                SearchResult(
                    segment_id=uuid.uuid4(),
                    content="Revenue was $10M",
                    score=0.9,
                    source_url="file:///r.md",
                    document_title="Report",
                    section_path="Q1",
                )
            ]
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )

        events = []
        async for event in agent.answer_streaming("What was the revenue?"):
            events.append(event)

        # Collect all token events
        token_events = [e for e in events if e["type"] == "token"]
        combined_answer = "".join(e["content"] for e in token_events)
        assert "10M" in combined_answer

        # The answer must appear exactly once — no duplicate streaming call
        mock_client.messages.stream.assert_not_called()

        # Verify we got exactly one done event
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_simple_answer_no_phase_b(self, mock_anthropic_cls):
        """When no tools are used, Phase B should not fire either."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_response([_make_text_block("Direct answer.")]))
        mock_client.messages.stream = Mock()
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_embedder = AsyncMock()

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )

        events = []
        async for event in agent.answer_streaming("Simple question?"):
            events.append(event)

        token_events = [e for e in events if e["type"] == "token"]
        combined = "".join(e["content"] for e in token_events)
        assert "Direct answer." in combined

        # No streaming call should have been made
        mock_client.messages.stream.assert_not_called()


class TestAnswerStreaming:
    """Tests for answer_streaming() — direct answers, tool use, and max iterations."""

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_direct_answer_streaming(self, mock_anthropic_cls):
        """Streaming returns token events for a direct answer (no tool use)."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_response([_make_text_block("Direct streaming answer.")])
        )
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_embedder = AsyncMock()

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )

        events = []
        async for event in agent.answer_streaming("Simple question?"):
            events.append(event)

        # Should have status, token(s), and done events
        event_types = [e["type"] for e in events]
        assert "status" in event_types
        assert "token" in event_types
        assert "done" in event_types

        # Verify the answer text is present
        token_events = [e for e in events if e["type"] == "token"]
        combined = "".join(e["content"] for e in token_events)
        assert "Direct streaming answer." in combined

        # Verify done metadata
        done_event = next(e for e in events if e["type"] == "done")
        assert "token_usage" in done_event["metadata"]
        assert done_event["metadata"]["tool_calls"] == 0

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_tool_use_then_streaming_final_answer(self, mock_anthropic_cls):
        """After tool use + end_turn in loop, Phase B streams the final answer."""
        mock_client = AsyncMock()

        # First call: tool_use
        tool_response = _make_response(
            [_make_tool_use_block("search_knowledge", {"query": "revenue"})],
            stop_reason="tool_use",
        )
        # Second call: tool_use again (to test multi-round)
        tool_response2 = _make_response(
            [_make_tool_use_block("search_knowledge", {"query": "revenue details"}, tool_id="tool_2")],
            stop_reason="tool_use",
        )
        # Third call: end_turn (but we went through tools, so Phase B fires)
        final_text_response = _make_response(
            [_make_text_block("Revenue was $10M.")],
            stop_reason="end_turn",
        )
        mock_client.messages.create = AsyncMock(side_effect=[tool_response, tool_response2, final_text_response])

        # Set up mock for Phase B streaming (should NOT be called since end_turn was hit)
        mock_client.messages.stream = Mock()
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(
            return_value=[
                SearchResult(
                    segment_id=uuid.uuid4(),
                    content="Revenue was $10M",
                    score=0.9,
                    source_url="file:///r.md",
                    document_title="Report",
                    section_path="Q1",
                )
            ]
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )

        events = []
        async for event in agent.answer_streaming("What was the revenue?"):
            events.append(event)

        # Should have tool-use status events
        status_events = [e for e in events if e["type"] == "status"]
        assert any("Search Knowledge" in e["content"] for e in status_events)

        # The answer was emitted via chunked tokens (end_turn path in the loop)
        token_events = [e for e in events if e["type"] == "token"]
        combined = "".join(e["content"] for e in token_events)
        assert "10M" in combined

        # Done event with correct tool_calls count
        done_event = next(e for e in events if e["type"] == "done")
        assert done_event["metadata"]["tool_calls"] == 2

        # Citations should be emitted
        citation_events = [e for e in events if e["type"] == "citation"]
        assert len(citation_events) >= 1

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_max_iterations_streaming(self, mock_anthropic_cls):
        """Streaming yields a warning status when max iterations is reached."""
        mock_client = AsyncMock()
        # Always return tool_use, never end_turn — will exhaust MAX_TOOL_ITERATIONS
        mock_client.messages.create = AsyncMock(
            return_value=_make_response(
                [_make_tool_use_block("search_knowledge", {"query": "x"})],
                stop_reason="tool_use",
            )
        )

        # Phase B streaming mock (will be called since tool_call_count > 0 and not answer_already_emitted)
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)

        async def empty_text_stream():
            yield "Max iterations fallback answer."

        mock_stream.text_stream = empty_text_stream()
        final_msg = Mock()
        final_msg.usage = Mock(input_tokens=50, output_tokens=25)
        mock_stream.get_final_message = AsyncMock(return_value=final_msg)
        mock_client.messages.stream = Mock(return_value=mock_stream)

        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )

        events = []
        async for event in agent.answer_streaming("infinite loop?"):
            events.append(event)

        # Should have the max-iterations warning status
        status_events = [e for e in events if e["type"] == "status"]
        assert any("maximum search iterations" in e["content"].lower() for e in status_events)

        # Should have a done event
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["metadata"]["tool_calls"] == 5


class TestSearchEntities:
    """Tests for the _search_entities tool method."""

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_no_db_session(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = AsyncMock()
        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            db_session=None,
        )
        result_text, citations = await agent._search_entities({"search_term": "revenue"})
        assert "not available" in result_text.lower()
        assert citations == []

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_no_matching_entities(self, mock_anthropic_cls):
        mock_anthropic_cls.return_value = AsyncMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            db_session=mock_session,
        )
        result_text, citations = await agent._search_entities({"search_term": "nonexistent"})
        assert "no matching" in result_text.lower()
        assert citations == []

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_returns_matching_entities(self, mock_anthropic_cls):
        """Tests the JSONB cast + ILIKE query pattern returns formatted entities."""
        mock_anthropic_cls.return_value = AsyncMock()
        mock_session = AsyncMock()

        entity1 = MagicMock()
        entity1.entity_type = "metric_definition"
        entity1.entity_data = {"name": "Revenue", "formula": "SUM(amount)"}
        entity1.confidence = 0.95

        entity2 = MagicMock()
        entity2.entity_type = "kpi_target"
        entity2.entity_data = {"name": "Monthly Revenue Target", "value": "$1M"}
        entity2.confidence = 0.88

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [entity1, entity2]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            db_session=mock_session,
        )
        result_text, citations = await agent._search_entities(
            {"search_term": "revenue", "entity_type": "metric_definition", "limit": 5}
        )
        assert "2 entities" in result_text
        assert "metric_definition" in result_text
        assert "Revenue" in result_text
        assert "95.0%" in result_text
        assert citations == []

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_dispatch_search_entities(self, mock_anthropic_cls):
        """Verify _execute_tool dispatches to _search_entities correctly."""
        mock_anthropic_cls.return_value = AsyncMock()
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            db_session=mock_session,
        )
        result_text, citations = await agent._execute_tool("search_entities", {"search_term": "test"})
        assert "no matching" in result_text.lower()
