"""Tests for graph schema initialization and management."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pam.graph.schema import (
    CONSTRAINTS,
    INDEXES,
    clear_graph,
    drop_schema,
    initialize_schema,
)


@pytest.fixture
def mock_graph_client():
    client = AsyncMock()
    client.execute_write = AsyncMock(return_value=[])
    client.execute_read = AsyncMock(return_value=[])
    return client


class TestInitializeSchema:
    async def test_creates_all_constraints(self, mock_graph_client):
        await initialize_schema(mock_graph_client)
        constraint_calls = [
            call.args[0]
            for call in mock_graph_client.execute_write.call_args_list
            if "CONSTRAINT" in call.args[0]
        ]
        assert len(constraint_calls) == len(CONSTRAINTS)

    async def test_creates_all_indexes(self, mock_graph_client):
        await initialize_schema(mock_graph_client)
        index_calls = [
            call.args[0]
            for call in mock_graph_client.execute_write.call_args_list
            if "INDEX" in call.args[0]
        ]
        assert len(index_calls) == len(INDEXES)

    async def test_total_statements_executed(self, mock_graph_client):
        await initialize_schema(mock_graph_client)
        assert mock_graph_client.execute_write.call_count == len(CONSTRAINTS) + len(INDEXES)

    async def test_constraints_use_if_not_exists(self):
        for stmt in CONSTRAINTS:
            assert "IF NOT EXISTS" in stmt, f"Constraint missing IF NOT EXISTS: {stmt}"

    async def test_indexes_use_if_not_exists(self):
        for stmt in INDEXES:
            assert "IF NOT EXISTS" in stmt, f"Index missing IF NOT EXISTS: {stmt}"


class TestDropSchema:
    async def test_drops_all_constraints(self, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [
            [{"name": "c1"}, {"name": "c2"}],  # constraints
            [],  # indexes
        ]
        await drop_schema(mock_graph_client)
        write_calls = [str(c) for c in mock_graph_client.execute_write.call_args_list]
        assert any("DROP CONSTRAINT c1" in c for c in write_calls)
        assert any("DROP CONSTRAINT c2" in c for c in write_calls)

    async def test_drops_all_indexes(self, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [
            [],  # constraints
            [{"name": "idx1"}],  # indexes
        ]
        await drop_schema(mock_graph_client)
        write_calls = [str(c) for c in mock_graph_client.execute_write.call_args_list]
        assert any("DROP INDEX idx1" in c for c in write_calls)

    async def test_handles_empty_schema(self, mock_graph_client):
        mock_graph_client.execute_read.side_effect = [[], []]
        await drop_schema(mock_graph_client)
        mock_graph_client.execute_write.assert_not_called()


class TestClearGraph:
    async def test_deletes_all_nodes_and_relationships(self, mock_graph_client):
        await clear_graph(mock_graph_client)
        mock_graph_client.execute_write.assert_awaited_once_with("MATCH (n) DETACH DELETE n")
