"""Tests for MCP graph tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_graph_search_returns_edges(mock_services: PamServices):
    """pam_graph_search returns relationship edges from Graphiti."""
    mock_edge = MagicMock()
    mock_edge.fact = "AuthService depends on UserDB"
    mock_edge.source_node_name = "AuthService"
    mock_edge.target_node_name = "UserDB"
    mock_edge.name = "DEPENDS_ON"

    mock_services.graph_service.client.search = AsyncMock(return_value=[mock_edge])

    from pam.mcp.server import _pam_graph_search

    result = await _pam_graph_search(query="AuthService dependencies")
    parsed = json.loads(result)

    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["fact"] == "AuthService depends on UserDB"
    assert parsed["results"][0]["source_name"] == "AuthService"


@pytest.mark.asyncio
async def test_pam_graph_search_unavailable(mock_services: PamServices):
    """pam_graph_search returns error when graph service is None."""
    mock_services.graph_service = None
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_graph_search

    result = await _pam_graph_search(query="test")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "unavailable" in parsed["error"].lower()


@pytest.mark.asyncio
async def test_pam_graph_neighbors(mock_services: PamServices):
    """pam_graph_neighbors returns 1-hop neighborhood."""
    mock_edge = MagicMock()
    mock_edge.fact = "AuthService uses Redis for sessions"
    mock_edge.source_node_name = "AuthService"
    mock_edge.target_node_name = "Redis"
    mock_edge.name = "USES"

    mock_services.graph_service.client.search = AsyncMock(return_value=[mock_edge])

    from pam.mcp.server import _pam_graph_neighbors

    result = await _pam_graph_neighbors(entity_name="AuthService")
    parsed = json.loads(result)

    assert parsed["entity"] == "AuthService"
    assert len(parsed["neighbors"]) == 1
    assert parsed["neighbors"][0]["name"] == "Redis"


@pytest.mark.asyncio
async def test_pam_entity_history(mock_services: PamServices):
    """pam_entity_history returns temporal snapshots."""
    mock_edge = MagicMock()
    mock_edge.fact = "AuthService was migrated to v2"
    mock_edge.created_at = "2026-02-01T00:00:00Z"
    mock_edge.name = "MIGRATED_TO"

    mock_services.graph_service.client.search = AsyncMock(return_value=[mock_edge])

    from pam.mcp.server import _pam_entity_history

    result = await _pam_entity_history(entity_name="AuthService", since=None)
    parsed = json.loads(result)

    assert parsed["entity"] == "AuthService"
    assert len(parsed["history"]) == 1
