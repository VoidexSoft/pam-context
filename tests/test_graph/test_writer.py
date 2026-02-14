"""Tests for graph writer — node/edge upserts to Neo4j."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from pam.graph.mapper import NodeData
from pam.graph.relationship_extractor import ExtractedRelationship
from pam.graph.writer import GraphWriter


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.execute_write = AsyncMock(return_value=[])
    return client


@pytest.fixture
def writer(mock_client):
    return GraphWriter(mock_client)


def _metric_node(name: str, **kwargs) -> NodeData:
    return NodeData(
        label="Metric",
        properties={"name": name, "confidence": 0.8, **kwargs},
        unique_key="name",
    )


def _team_node(name: str) -> NodeData:
    return NodeData(label="Team", properties={"name": name}, unique_key="name")


class TestUpsertNode:
    async def test_merges_single_node(self, writer, mock_client):
        node = _metric_node("DAU", formula="count(users)")
        await writer.upsert_node(node)

        mock_client.execute_write.assert_awaited_once()
        query = mock_client.execute_write.call_args[0][0]
        assert "MERGE" in query
        assert "Metric" in query
        assert "name" in query

    async def test_skips_none_properties(self, writer, mock_client):
        node = NodeData(
            label="Metric",
            properties={"name": "DAU", "formula": None, "owner": None},
            unique_key="name",
        )
        await writer.upsert_node(node)
        params = mock_client.execute_write.call_args[0][1]
        assert "formula" not in params
        assert "owner" not in params


class TestUpsertNodesBatch:
    async def test_batch_upsert_groups_by_label(self, writer, mock_client):
        nodes = [
            _metric_node("DAU"),
            _metric_node("MRR"),
            _team_node("Growth"),
        ]
        await writer.upsert_nodes_batch(nodes)
        # Two calls: one for Metric (2 nodes), one for Team (1 node)
        assert mock_client.execute_write.call_count == 2

    async def test_batch_uses_unwind(self, writer, mock_client):
        nodes = [_metric_node("DAU"), _metric_node("MRR")]
        await writer.upsert_nodes_batch(nodes)

        query = mock_client.execute_write.call_args[0][0]
        assert "UNWIND" in query

    async def test_empty_batch_is_noop(self, writer, mock_client):
        await writer.upsert_nodes_batch([])
        mock_client.execute_write.assert_not_called()


class TestUpsertRelationship:
    async def test_creates_relationship(self, writer, mock_client):
        await writer.upsert_relationship(
            from_label="Metric", from_key="name", from_value="Conv Rate",
            rel_type="DEPENDS_ON",
            to_label="Metric", to_key="name", to_value="Signups",
            properties={"confidence": 0.85},
        )

        query = mock_client.execute_write.call_args[0][0]
        assert "MERGE" in query
        assert "DEPENDS_ON" in query
        assert "Metric" in query

    async def test_sets_temporal_defaults(self, writer, mock_client):
        await writer.upsert_relationship(
            from_label="Event", from_key="name", from_value="signup",
            rel_type="TRACKED_BY",
            to_label="Metric", to_key="name", to_value="DAU",
        )
        params = mock_client.execute_write.call_args[0][1]
        assert "valid_from" in params
        assert "created_at" in params


class TestWriteRelationships:
    async def test_writes_all_relationships(self, writer, mock_client):
        rels = [
            ExtractedRelationship("A", "Metric", "DEPENDS_ON", "B", "Metric", 0.8),
            ExtractedRelationship("ev1", "Event", "TRACKED_BY", "A", "Metric", 0.7),
        ]
        await writer.write_relationships(rels)
        assert mock_client.execute_write.call_count == 2


class TestWriteDocumentEdges:
    async def test_creates_document_node(self, writer, mock_client):
        await writer.write_document_edges("doc-123", "My Doc", [])
        query = mock_client.execute_write.call_args[0][0]
        assert "Document" in query
        assert "MERGE" in query

    async def test_creates_defined_in_edges(self, writer, mock_client):
        nodes = [_metric_node("DAU")]
        await writer.write_document_edges("doc-123", "My Doc", nodes)
        # 1 for document node + 1 for DEFINED_IN edge
        assert mock_client.execute_write.call_count == 2
        edge_query = mock_client.execute_write.call_args_list[1][0][0]
        assert "DEFINED_IN" in edge_query


class TestWriteImplicitEdges:
    async def test_creates_owned_by_edge(self, writer, mock_client):
        node = _metric_node("DAU", owner="Growth")
        await writer.write_implicit_edges([node])
        queries = [c[0][0] for c in mock_client.execute_write.call_args_list]
        assert any("OWNED_BY" in q for q in queries)

    async def test_creates_sourced_from_edge(self, writer, mock_client):
        node = _metric_node("DAU", data_source="Mixpanel")
        await writer.write_implicit_edges([node])
        queries = [c[0][0] for c in mock_client.execute_write.call_args_list]
        assert any("SOURCED_FROM" in q for q in queries)

    async def test_skips_nodes_without_owner(self, writer, mock_client):
        node = _metric_node("DAU")
        await writer.write_implicit_edges([node])
        mock_client.execute_write.assert_not_called()


class TestCloseTemporalEdge:
    async def test_sets_valid_to(self, writer, mock_client):
        await writer.close_temporal_edge(
            from_label="Metric", from_key="name", from_value="DAU",
            rel_type="DEFINED_IN",
            to_label="Document", to_key="id", to_value="doc-1",
        )
        query = mock_client.execute_write.call_args[0][0]
        assert "valid_to" in query
        assert "WHERE r.valid_to IS NULL" in query
