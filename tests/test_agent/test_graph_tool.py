"""Tests for the query_graph agent tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.agent.agent import RetrievalAgent


@pytest.fixture
def mock_graph_query_service():
    service = AsyncMock()
    service.find_dependencies = AsyncMock(return_value=[])
    service.find_related = AsyncMock(return_value=[])
    service.get_entity_history = AsyncMock(return_value=[])
    service.execute_cypher = AsyncMock(return_value=[])
    return service


@pytest.fixture
def agent(mock_graph_query_service):
    """Create agent with mocked dependencies and graph query service."""
    return RetrievalAgent(
        search_service=AsyncMock(),
        embedder=AsyncMock(),
        api_key="test-key",
        model="test-model",
        db_session=AsyncMock(),
        graph_query_service=mock_graph_query_service,
    )


class TestQueryGraphDependencies:
    async def test_finds_dependencies(self, agent, mock_graph_query_service):
        mock_graph_query_service.find_dependencies.return_value = [
            {"name": "Signups", "direction": "depends_on", "confidence": 0.9, "since": "2026-01-01"},
            {"name": "Revenue", "direction": "depended_by", "confidence": 0.8, "since": "2026-01-01"},
        ]
        result, citations = await agent._query_graph({"query_type": "dependencies", "entity_name": "DAU"})
        assert "depends on" in result
        assert "Signups" in result
        assert "depended on by" in result
        assert "Revenue" in result

    async def test_no_dependencies(self, agent, mock_graph_query_service):
        result, _ = await agent._query_graph({"query_type": "dependencies", "entity_name": "Orphan"})
        assert "No dependencies found" in result

    async def test_requires_entity_name(self, agent):
        result, _ = await agent._query_graph({"query_type": "dependencies"})
        assert "entity_name" in result


class TestQueryGraphRelated:
    async def test_finds_related(self, agent, mock_graph_query_service):
        mock_graph_query_service.find_related.return_value = [
            {"from_name": "DAU", "from_label": "Metric", "rel_type": "OWNED_BY",
             "to_name": "Growth", "to_label": "Team", "confidence": None},
        ]
        result, _ = await agent._query_graph({"query_type": "related", "entity_name": "DAU"})
        assert "OWNED_BY" in result
        assert "Growth" in result

    async def test_passes_max_depth(self, agent, mock_graph_query_service):
        await agent._query_graph({"query_type": "related", "entity_name": "DAU", "max_depth": 3})
        mock_graph_query_service.find_related.assert_awaited_once_with("DAU", 3)


class TestQueryGraphHistory:
    async def test_finds_history(self, agent, mock_graph_query_service):
        mock_graph_query_service.get_entity_history.return_value = [
            {"rel_type": "DEFINED_IN", "target_name": "Metrics Guide", "target_label": "Document",
             "valid_from": "2026-01-01", "valid_to": None, "document_title": "Metrics Guide"},
        ]
        result, _ = await agent._query_graph({"query_type": "history", "entity_name": "DAU"})
        assert "DEFINED_IN" in result
        assert "Metrics Guide" in result

    async def test_passes_since(self, agent, mock_graph_query_service):
        await agent._query_graph({"query_type": "history", "entity_name": "DAU", "since": "2026-02-01"})
        mock_graph_query_service.get_entity_history.assert_awaited_once_with("DAU", "2026-02-01")


class TestQueryGraphCypher:
    async def test_executes_cypher(self, agent, mock_graph_query_service):
        mock_graph_query_service.execute_cypher.return_value = [{"count": 42}]
        result, _ = await agent._query_graph({"query_type": "cypher", "cypher": "MATCH (n) RETURN count(n) AS count"})
        assert "42" in result

    async def test_handles_write_rejection(self, agent, mock_graph_query_service):
        mock_graph_query_service.execute_cypher.side_effect = ValueError("Write operations not allowed")
        result, _ = await agent._query_graph({"query_type": "cypher", "cypher": "MERGE (n:Test) RETURN n"})
        assert "Query error" in result
        assert "Write" in result

    async def test_requires_cypher_string(self, agent):
        result, _ = await agent._query_graph({"query_type": "cypher"})
        assert "cypher" in result.lower()


class TestQueryGraphEdgeCases:
    async def test_graph_not_available(self):
        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            api_key="test-key",
            graph_query_service=None,
        )
        result, _ = await agent._query_graph({"query_type": "dependencies", "entity_name": "DAU"})
        assert "not available" in result

    async def test_unknown_query_type(self, agent):
        result, _ = await agent._query_graph({"query_type": "invalid"})
        assert "Unknown query_type" in result

    async def test_handles_unexpected_error(self, agent, mock_graph_query_service):
        mock_graph_query_service.find_dependencies.side_effect = RuntimeError("Neo4j down")
        result, _ = await agent._query_graph({"query_type": "dependencies", "entity_name": "DAU"})
        assert "error occurred" in result
