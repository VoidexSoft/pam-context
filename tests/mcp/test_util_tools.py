"""Tests for MCP utility tools."""

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
async def test_pam_query_data_executes_sql(mock_services: PamServices):
    """pam_query_data runs a SQL query via DuckDB."""
    mock_services.duckdb_service.query.return_value = {
        "columns": ["name", "revenue"],
        "rows": [["Product A", 1000], ["Product B", 2000]],
        "row_count": 2,
    }

    from pam.mcp.server import _pam_query_data

    result = await _pam_query_data(sql="SELECT name, revenue FROM products", list_tables=False)
    parsed = json.loads(result)

    assert parsed["row_count"] == 2
    assert parsed["columns"] == ["name", "revenue"]
    mock_services.duckdb_service.query.assert_called_once()


@pytest.mark.asyncio
async def test_pam_query_data_list_tables(mock_services: PamServices):
    """pam_query_data lists available tables when list_tables=True."""
    mock_services.duckdb_service.list_tables.return_value = {
        "tables": [{"name": "products", "columns": ["name", "revenue"]}],
    }

    from pam.mcp.server import _pam_query_data

    result = await _pam_query_data(sql=None, list_tables=True)
    parsed = json.loads(result)

    assert "tables" in parsed
    mock_services.duckdb_service.list_tables.assert_called_once()


@pytest.mark.asyncio
async def test_pam_query_data_unavailable(mock_services: PamServices):
    """pam_query_data returns error when DuckDB is not configured."""
    mock_services.duckdb_service = None
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_query_data

    result = await _pam_query_data(sql="SELECT 1", list_tables=False)
    parsed = json.loads(result)

    assert "error" in parsed
