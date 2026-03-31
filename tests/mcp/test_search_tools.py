"""Tests for MCP search tools."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.server import create_mcp_server
from pam.mcp.services import PamServices
from pam.retrieval.types import SearchResult


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    """Initialize MCP services for every test in this module."""
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


def test_create_mcp_server():
    """Server can be created without errors."""
    server = create_mcp_server()
    assert server is not None
    assert server.name == "PAM Context"


def test_pam_services_fields():
    """PamServices has all expected fields."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(PamServices)}
    assert "search_service" in fields
    assert "embedder" in fields
    assert "session_factory" in fields
    assert "es_client" in fields
    assert "graph_service" in fields
    assert "vdb_store" in fields
    assert "duckdb_service" in fields
    assert "cache_service" in fields


@pytest.mark.asyncio
async def test_pam_search_returns_results(mock_services: PamServices):
    """pam_search calls search_service and returns JSON results."""
    segment_id = uuid.uuid4()
    mock_services.embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    mock_services.search_service.search = AsyncMock(
        return_value=[
            SearchResult(
                segment_id=segment_id,
                content="Revenue grew 15% YoY",
                score=0.95,
                document_title="Q1 Report",
                section_path="financials > revenue",
                source_url="/docs/q1-report.md",
            ),
        ]
    )

    from pam.mcp.server import _pam_search

    result = await _pam_search(query="revenue growth", limit=5, source_type=None)
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["content"] == "Revenue grew 15% YoY"
    assert parsed[0]["document_title"] == "Q1 Report"
    mock_services.embedder.embed_texts.assert_awaited_once_with(["revenue growth"])
    mock_services.search_service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_search_with_source_filter(mock_services: PamServices):
    """pam_search passes source_type filter to search service."""
    mock_services.embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    mock_services.search_service.search = AsyncMock(return_value=[])

    from pam.mcp.server import _pam_search

    result = await _pam_search(query="test", limit=3, source_type="markdown")
    parsed = json.loads(result)

    assert parsed == []
    call_kwargs = mock_services.search_service.search.call_args
    assert call_kwargs.kwargs.get("source_type") == "markdown"
    assert call_kwargs.kwargs.get("top_k") == 3


@pytest.mark.asyncio
async def test_pam_smart_search_concurrent_results(mock_services: PamServices):
    """pam_smart_search runs ES + graph + VDB searches concurrently."""
    mock_services.embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    mock_services.search_service.search = AsyncMock(
        return_value=[
            SearchResult(
                segment_id=uuid.uuid4(),
                content="ES result",
                score=0.9,
                document_title="Doc A",
            ),
        ]
    )
    mock_services.graph_service.client.search = AsyncMock(return_value=[])
    mock_services.vdb_store.search_entities = AsyncMock(return_value=[])
    mock_services.vdb_store.search_relationships = AsyncMock(return_value=[])

    from pam.mcp.server import _pam_smart_search

    result = await _pam_smart_search(query="revenue targets")
    parsed = json.loads(result)

    assert "documents" in parsed
    assert len(parsed["documents"]) == 1
    assert parsed["documents"][0]["content"] == "ES result"
    mock_services.search_service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_smart_search_graph_unavailable(mock_services: PamServices):
    """pam_smart_search gracefully handles graph service being None."""
    mock_services.graph_service = None
    mock_services.vdb_store = None
    mock_services.embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    mock_services.search_service.search = AsyncMock(return_value=[])

    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_smart_search

    result = await _pam_smart_search(query="test")
    parsed = json.loads(result)

    assert "documents" in parsed
    assert parsed["graph"] == []
    assert parsed["entities"] == []
