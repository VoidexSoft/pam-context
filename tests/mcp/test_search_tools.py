"""Tests for MCP search tools."""

from pam.mcp.server import create_mcp_server


def test_create_mcp_server():
    """Server can be created without errors."""
    server = create_mcp_server()
    assert server is not None
    assert server.name == "PAM Context"


from pam.mcp.services import PamServices


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
