"""MCP server definition with tool and resource registrations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from pam.mcp.services import PamServices

logger = structlog.get_logger()

_services: PamServices | None = None


def get_services() -> PamServices:
    """Return the initialized PamServices instance.

    Raises AssertionError if called before initialize().
    """
    if _services is None:
        msg = "MCP services not initialized — call initialize() first"
        raise RuntimeError(msg)
    return _services


def initialize(services: PamServices) -> None:
    """Set the global services instance. Called once at startup."""
    global _services  # noqa: PLW0603
    _services = services


def create_mcp_server() -> FastMCP:
    """Create and return the FastMCP server with all tools registered."""
    mcp = FastMCP(
        "PAM Context",
        instructions="Business Knowledge Layer for LLMs — search documents, query knowledge graph, trigger ingestion",
    )
    _register_search_tools(mcp)
    _register_document_tools(mcp)
    _register_graph_tools(mcp)
    _register_utility_tools(mcp)
    _register_resources(mcp)
    return mcp


def _register_search_tools(mcp: FastMCP) -> None:
    """Register search-related MCP tools. Implemented in Task 3-4."""
    pass


def _register_document_tools(mcp: FastMCP) -> None:
    """Register document-related MCP tools. Implemented in Task 5."""
    pass


def _register_graph_tools(mcp: FastMCP) -> None:
    """Register graph-related MCP tools. Implemented in Task 6."""
    pass


def _register_utility_tools(mcp: FastMCP) -> None:
    """Register utility MCP tools. Implemented in Task 7."""
    pass


def _register_resources(mcp: FastMCP) -> None:
    """Register MCP resources. Implemented in Task 8."""
    pass
