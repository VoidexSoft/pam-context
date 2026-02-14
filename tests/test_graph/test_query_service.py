"""Tests for graph query service."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pam.graph.query_service import GraphQueryService


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.execute_read = AsyncMock(return_value=[])
    return client


@pytest.fixture
def service(mock_client):
    return GraphQueryService(mock_client, max_rows=50)


class TestFindDependencies:
    async def test_queries_both_directions(self, service, mock_client):
        mock_client.execute_read.return_value = [
            {"name": "Signups", "direction": "depends_on", "confidence": 0.9, "since": "2026-01-01"},
            {"name": "Revenue", "direction": "depended_by", "confidence": 0.8, "since": "2026-01-01"},
        ]
        result = await service.find_dependencies("DAU")
        assert len(result) == 2
        mock_client.execute_read.assert_awaited_once()
        query = mock_client.execute_read.call_args[0][0]
        assert "DEPENDS_ON" in query
        assert "UNION" in query

    async def test_returns_empty_for_unknown_entity(self, service, mock_client):
        result = await service.find_dependencies("NonExistent")
        assert result == []


class TestFindRelated:
    async def test_traverses_with_depth(self, service, mock_client):
        mock_client.execute_read.return_value = [
            {"from_name": "DAU", "from_label": "Metric", "rel_type": "OWNED_BY",
             "to_name": "Growth", "to_label": "Team", "confidence": None},
        ]
        result = await service.find_related("DAU", max_depth=2)
        assert len(result) == 1
        query = mock_client.execute_read.call_args[0][0]
        assert "*1..2" in query

    async def test_clamps_max_depth(self, service, mock_client):
        await service.find_related("DAU", max_depth=10)
        query = mock_client.execute_read.call_args[0][0]
        assert "*1..4" in query  # Clamped to max 4

    async def test_clamps_min_depth(self, service, mock_client):
        await service.find_related("DAU", max_depth=0)
        query = mock_client.execute_read.call_args[0][0]
        assert "*1..1" in query  # Clamped to min 1

    async def test_passes_row_limit(self, service, mock_client):
        await service.find_related("DAU")
        params = mock_client.execute_read.call_args[0][1]
        assert params["limit"] == 50


class TestGetEntityHistory:
    async def test_queries_temporal_edges(self, service, mock_client):
        mock_client.execute_read.return_value = [
            {"rel_type": "DEFINED_IN", "target_name": "metrics.md", "target_label": "Document",
             "valid_from": "2026-01-01", "valid_to": None, "document_title": "Metrics Guide"},
        ]
        result = await service.get_entity_history("DAU")
        assert len(result) == 1
        query = mock_client.execute_read.call_args[0][0]
        assert "valid_from" in query

    async def test_filters_by_since(self, service, mock_client):
        await service.get_entity_history("DAU", since="2026-02-01")
        query = mock_client.execute_read.call_args[0][0]
        params = mock_client.execute_read.call_args[0][1]
        assert "since" in params
        assert params["since"] == "2026-02-01"
        assert ">= $since" in query

    async def test_no_since_filter_when_none(self, service, mock_client):
        await service.get_entity_history("DAU")
        params = mock_client.execute_read.call_args[0][1]
        assert "since" not in params


class TestExecuteCypher:
    async def test_executes_read_query(self, service, mock_client):
        mock_client.execute_read.return_value = [{"count": 42}]
        result = await service.execute_cypher("MATCH (n) RETURN count(n) AS count")
        assert result == [{"count": 42}]

    async def test_rejects_merge(self, service):
        with pytest.raises(ValueError, match="Write operations"):
            await service.execute_cypher("MERGE (n:Test {name: 'x'}) RETURN n")

    async def test_rejects_create(self, service):
        with pytest.raises(ValueError, match="Write operations"):
            await service.execute_cypher("CREATE (n:Test) RETURN n")

    async def test_rejects_delete(self, service):
        with pytest.raises(ValueError, match="Write operations"):
            await service.execute_cypher("MATCH (n) DELETE n")

    async def test_rejects_set(self, service):
        with pytest.raises(ValueError, match="Write operations"):
            await service.execute_cypher("MATCH (n) SET n.name = 'x' RETURN n")

    async def test_rejects_detach_delete(self, service):
        with pytest.raises(ValueError, match="Write operations"):
            await service.execute_cypher("MATCH (n) DETACH DELETE n")

    async def test_injects_limit_if_missing(self, service, mock_client):
        await service.execute_cypher("MATCH (n) RETURN n")
        query = mock_client.execute_read.call_args[0][0]
        assert "LIMIT 50" in query

    async def test_preserves_existing_limit(self, service, mock_client):
        await service.execute_cypher("MATCH (n) RETURN n LIMIT 10")
        query = mock_client.execute_read.call_args[0][0]
        assert "LIMIT 10" in query
        assert "LIMIT 50" not in query

    async def test_passes_parameters(self, service, mock_client):
        await service.execute_cypher("MATCH (n {name: $name}) RETURN n", {"name": "DAU"})
        params = mock_client.execute_read.call_args[0][1]
        assert params["name"] == "DAU"
