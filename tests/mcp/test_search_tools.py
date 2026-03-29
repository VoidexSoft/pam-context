"""Tests for MCP search tools."""

from pam.mcp.server import create_mcp_server


def test_create_mcp_server():
    """Server can be created without errors."""
    server = create_mcp_server()
    assert server is not None
    assert server.name == "PAM Context"
