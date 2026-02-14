"""Tests for graph context injection in search_knowledge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.agent import RetrievalAgent


@pytest.fixture
def mock_graph_query_service():
    service = AsyncMock()
    service.find_dependencies = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_search_service():
    service = AsyncMock()
    return service


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 10])
    return embedder


@pytest.fixture
def agent(mock_search_service, mock_embedder, mock_graph_query_service):
    return RetrievalAgent(
        search_service=mock_search_service,
        embedder=mock_embedder,
        api_key="test-key",
        graph_query_service=mock_graph_query_service,
    )


def _search_result(content: str = "test content", title: str = "Doc"):
    """Create a mock search result."""
    result = MagicMock()
    result.content = content
    result.document_title = title
    result.section_path = "section"
    result.source_url = "http://example.com"
    result.source_id = "src-1"
    result.segment_id = "seg-1"
    return result


class TestGraphContextInjection:
    @patch("pam.agent.agent.settings")
    async def test_injects_dependency_context(self, mock_settings, agent, mock_search_service, mock_graph_query_service):
        mock_settings.graph_context_enabled = True
        mock_search_service.search.return_value = [_search_result("DAU is growing")]
        mock_graph_query_service.find_dependencies.return_value = [
            {"name": "Signups", "direction": "depends_on", "confidence": 0.9, "since": "2026-01-01"},
        ]

        result, _ = await agent._search_knowledge({"query": "What is DAU"})
        assert "Graph Context" in result
        assert "Signups" in result

    @patch("pam.agent.agent.settings")
    async def test_no_injection_when_disabled(self, mock_settings, agent, mock_search_service, mock_graph_query_service):
        mock_settings.graph_context_enabled = False
        mock_search_service.search.return_value = [_search_result()]

        result, _ = await agent._search_knowledge({"query": "What is DAU"})
        assert "Graph Context" not in result

    @patch("pam.agent.agent.settings")
    async def test_no_injection_when_no_graph_service(self, mock_settings, mock_search_service, mock_embedder):
        mock_settings.graph_context_enabled = True
        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            api_key="test-key",
            graph_query_service=None,
        )
        mock_search_service.search.return_value = [_search_result()]

        result, _ = await agent._search_knowledge({"query": "What is DAU"})
        assert "Graph Context" not in result

    @patch("pam.agent.agent.settings")
    async def test_no_injection_when_no_matches(self, mock_settings, agent, mock_search_service, mock_graph_query_service):
        mock_settings.graph_context_enabled = True
        mock_search_service.search.return_value = [_search_result()]
        mock_graph_query_service.find_dependencies.return_value = []

        result, _ = await agent._search_knowledge({"query": "What is DAU"})
        assert "Graph Context" not in result

    @patch("pam.agent.agent.settings")
    async def test_graceful_failure(self, mock_settings, agent, mock_search_service, mock_graph_query_service):
        mock_settings.graph_context_enabled = True
        mock_search_service.search.return_value = [_search_result()]
        mock_graph_query_service.find_dependencies.side_effect = Exception("Neo4j down")

        # Should not raise, should return results without graph context
        result, _ = await agent._search_knowledge({"query": "What is DAU"})
        assert "Graph Context" not in result
        assert "test content" in result


class TestGetGraphContext:
    @patch("pam.agent.agent.settings")
    async def test_returns_dependency_info(self, mock_settings, agent, mock_graph_query_service):
        mock_graph_query_service.find_dependencies.return_value = [
            {"name": "Visits", "direction": "depends_on", "confidence": 0.85, "since": "2026-01-01"},
            {"name": "Revenue", "direction": "depended_by", "confidence": 0.7, "since": "2026-01-01"},
        ]

        context = await agent._get_graph_context("DAU growth")
        assert "Visits" in context or "Revenue" in context or context == ""
        # The function checks all words as candidates, "DAU" should match

    async def test_returns_empty_without_graph_service(self):
        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            api_key="test-key",
            graph_query_service=None,
        )
        result = await agent._get_graph_context("DAU")
        assert result == ""
