"""Tests for graph API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_graph_client():
    client = AsyncMock()
    client.execute_read = AsyncMock(return_value=[])
    return client


@pytest.fixture
def app_with_graph(app, mock_graph_client):
    """App with graph_client set on state."""
    app.state.graph_client = mock_graph_client
    yield app
    del app.state.graph_client


class TestListEntities:
    async def test_returns_entities(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.return_value = [
            {"name": "DAU", "label": "Metric", "rel_count": 3, "version": 1, "entity_type": "metric_definition"},
            {"name": "MRR", "label": "Metric", "rel_count": 1, "version": 1, "entity_type": "metric_definition"},
        ]
        resp = await client.get("/api/graph/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "DAU"

    async def test_filter_by_label(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.return_value = [
            {"name": "PageView", "label": "Event", "rel_count": 0, "version": 1, "entity_type": "event"},
        ]
        resp = await client.get("/api/graph/entities?label=Event")
        assert resp.status_code == 200
        # Verify the Cypher contains :Event
        call_args = mock_graph_client.execute_read.call_args
        assert ":Event" in call_args[0][0]

    async def test_no_graph_returns_503(self, client):
        resp = await client.get("/api/graph/entities")
        assert resp.status_code == 503

    async def test_empty_graph(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.return_value = []
        resp = await client.get("/api/graph/entities")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetEntity:
    async def test_entity_found(self, client, app_with_graph, mock_graph_client):
        # First call returns node, second returns relationships
        mock_graph_client.execute_read.side_effect = [
            [{"n": {"name": "DAU", "formula": "count(distinct users)"}, "label": "Metric"}],
            [
                {"rel_type": "DEPENDS_ON", "target_name": "MAU", "target_label": "Metric",
                 "confidence": 0.9, "valid_from": "2026-01-01", "valid_to": None, "direction": "outgoing"},
            ],
        ]
        resp = await client.get("/api/graph/entity/DAU")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "DAU"
        assert data["label"] == "Metric"
        assert len(data["relationships"]) == 1
        assert data["relationships"][0]["rel_type"] == "DEPENDS_ON"

    async def test_entity_not_found(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [[], []]
        resp = await client.get("/api/graph/entity/Nonexistent")
        assert resp.status_code == 404

    async def test_no_graph_returns_503(self, client):
        resp = await client.get("/api/graph/entity/DAU")
        assert resp.status_code == 503


class TestGetSubgraph:
    async def test_returns_nodes_and_edges(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.return_value = [
            {"source_name": "DAU", "source_label": "Metric",
             "rel_type": "DEPENDS_ON", "target_name": "MAU", "target_label": "Metric", "confidence": 0.9},
            {"source_name": "DAU", "source_label": "Metric",
             "rel_type": "DEFINED_IN", "target_name": "Metrics Guide", "target_label": "Document", "confidence": None},
        ]
        resp = await client.get("/api/graph/subgraph?entity_name=DAU")
        assert resp.status_code == 200
        data = resp.json()
        assert data["center"] == "DAU"
        assert len(data["nodes"]) == 3  # DAU, MAU, Metrics Guide
        assert len(data["edges"]) == 2
        # Center node should be marked
        center = next(n for n in data["nodes"] if n["id"] == "DAU")
        assert center["isCenter"] is True

    async def test_entity_not_found(self, client, app_with_graph, mock_graph_client):
        # First call (subgraph) returns empty, second call (check) returns empty
        mock_graph_client.execute_read.side_effect = [[], []]
        resp = await client.get("/api/graph/subgraph?entity_name=Nonexistent")
        assert resp.status_code == 404

    async def test_isolated_entity(self, client, app_with_graph, mock_graph_client):
        # No edges but entity exists
        mock_graph_client.execute_read.side_effect = [
            [],  # subgraph query returns empty
            [{"name": "Lonely", "label": "Metric"}],  # check query finds it
        ]
        resp = await client.get("/api/graph/subgraph?entity_name=Lonely")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["isCenter"] is True

    async def test_depth_clamped(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.return_value = []
        # Try depth > 4
        resp = await client.get("/api/graph/subgraph?entity_name=X&depth=10")
        assert resp.status_code == 422  # validation error from Query(ge=1, le=4)

    async def test_no_graph_returns_503(self, client):
        resp = await client.get("/api/graph/subgraph?entity_name=DAU")
        assert resp.status_code == 503


class TestGetTimeline:
    async def test_returns_history(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [
            [
                {"rel_type": "DEFINED_IN", "target_name": "Metrics Guide", "target_label": "Document",
                 "valid_from": "2026-01-01", "valid_to": None, "confidence": None},
                {"rel_type": "OWNED_BY", "target_name": "Growth", "target_label": "Team",
                 "valid_from": "2026-01-15", "valid_to": "2026-02-01", "confidence": None},
            ],
            [{"label": "Metric", "version": 3}],  # meta query
        ]
        resp = await client.get("/api/graph/timeline/DAU")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_name"] == "DAU"
        assert data["label"] == "Metric"
        assert data["version"] == 3
        assert len(data["history"]) == 2

    async def test_with_since_filter(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [
            [{"rel_type": "DEFINED_IN", "target_name": "Doc", "target_label": "Document",
              "valid_from": "2026-02-01", "valid_to": None, "confidence": None}],
            [{"label": "Metric", "version": 2}],
        ]
        resp = await client.get("/api/graph/timeline/DAU?since=2026-02-01")
        assert resp.status_code == 200
        # Verify since clause is in the query
        call_args = mock_graph_client.execute_read.call_args_list[0]
        assert "since" in call_args[0][1]

    async def test_empty_history(self, client, app_with_graph, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [
            [],
            [{"label": "Metric", "version": 1}],
        ]
        resp = await client.get("/api/graph/timeline/DAU")
        assert resp.status_code == 200
        assert resp.json()["history"] == []

    async def test_no_graph_returns_503(self, client):
        resp = await client.get("/api/graph/timeline/DAU")
        assert resp.status_code == 503
