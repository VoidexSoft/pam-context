"""MCP server definition with tool and resource registrations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

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

    @mcp.tool()
    async def pam_smart_search(
        query: str,
        mode: str | None = None,
    ) -> str:
        """Search documents AND the knowledge graph in one call.

        Runs hybrid document search, graph relationship search, entity VDB search,
        and relationship VDB search concurrently. Returns results in separate sections.
        Optional mode: entity, conceptual, temporal, factual, hybrid.
        """
        return await _pam_smart_search(query=query, mode=mode)


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


async def _pam_smart_search(
    query: str,
    mode: str | None = None,
) -> str:
    """Implementation of pam_smart_search — concurrent 4-way search."""
    import asyncio

    services = get_services()
    embedding = await services.embedder.embed(query)

    # Build concurrent tasks
    tasks: dict[str, Any] = {}
    tasks["documents"] = services.search_service.search(
        query=query, query_embedding=embedding, top_k=5,
    )
    if services.graph_service is not None:
        tasks["graph"] = services.graph_service.client.search(query=query, num_results=5)
    if services.vdb_store is not None:
        tasks["entities"] = services.vdb_store.search_entities(
            query_embedding=embedding, top_k=5,
        )
        tasks["relationships"] = services.vdb_store.search_relationships(
            query_embedding=embedding, top_k=5,
        )

    keys = list(tasks.keys())
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results_map: dict[str, Any] = {}
    for key, result in zip(keys, results_list):
        if isinstance(result, Exception):
            logger.warning("smart_search_partial_failure", source=key, error=str(result))
            results_map[key] = []
        else:
            results_map[key] = result

    doc_results = [
        {
            "segment_id": str(r.segment_id),
            "content": r.content,
            "score": r.score,
            "document_title": r.document_title,
            "section_path": r.section_path,
            "source_url": r.source_url,
        }
        for r in results_map.get("documents", [])
    ]

    graph_results = []
    for edge in results_map.get("graph", []):
        graph_results.append({
            "fact": getattr(edge, "fact", str(edge)),
            "source_name": getattr(edge, "source_node_name", None),
            "target_name": getattr(edge, "target_node_name", None),
            "relation_type": getattr(edge, "name", None),
        })

    entity_results = []
    for hit in results_map.get("entities", []):
        entity_results.append({
            "name": hit.get("name", ""),
            "type": hit.get("entity_type", ""),
            "description": hit.get("description", ""),
            "score": hit.get("score", 0),
        })

    rel_results = []
    for hit in results_map.get("relationships", []):
        rel_results.append({
            "src_entity": hit.get("src_entity", ""),
            "tgt_entity": hit.get("tgt_entity", ""),
            "rel_type": hit.get("rel_type", ""),
            "keywords": hit.get("keywords", ""),
            "score": hit.get("score", 0),
        })

    return json.dumps(
        {
            "documents": doc_results,
            "graph": graph_results,
            "entities": entity_results,
            "relationships": rel_results,
            "mode": mode,
        },
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
