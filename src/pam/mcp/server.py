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
    """Register search-related MCP tools."""

    @mcp.tool()
    async def pam_search(
        query: str,
        limit: int = 5,
        source_type: str | None = None,
    ) -> str:
        """Search PAM's knowledge base with hybrid BM25 + vector search.

        Returns relevant document segments with source citations, scores, and
        section paths. Use this for factual lookups, definitions, and document Q&A.
        """
        return await _pam_search(query=query, limit=limit, source_type=source_type)

    # pam_smart_search registered in Task 4


async def _pam_search(
    query: str,
    limit: int = 5,
    source_type: str | None = None,
) -> str:
    """Implementation of pam_search, extracted for direct testing."""
    services = get_services()
    embedding = await services.embedder.embed(query)
    results = await services.search_service.search(
        query=query,
        query_embedding=embedding,
        top_k=limit,
        source_type=source_type,
    )
    return json.dumps(
        [
            {
                "segment_id": str(r.segment_id),
                "content": r.content,
                "score": r.score,
                "document_title": r.document_title,
                "section_path": r.section_path,
                "source_url": r.source_url,
            }
            for r in results
        ],
        indent=2,
    )


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
