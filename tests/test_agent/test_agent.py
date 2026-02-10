"""Tests for RetrievalAgent — tool-use loop with mocked Anthropic + search."""

import uuid
from unittest.mock import AsyncMock, Mock, patch

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
        mock_client.messages.create = AsyncMock(
            return_value=_make_response([_make_text_block("The answer is 42.")])
        )
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
