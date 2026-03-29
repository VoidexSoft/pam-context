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
    """Register document-related MCP tools."""

    @mcp.tool()
    async def pam_get_document(
        document_title: str | None = None,
        source_id: str | None = None,
    ) -> str:
        """Fetch the full content of a specific document for deep reading.

        Provide either document_title or source_id. Returns the document
        metadata and all its segments (chunks) in order.
        """
        return await _pam_get_document(document_title=document_title, source_id=source_id)

    @mcp.tool()
    async def pam_list_documents(
        limit: int = 20,
        source_type: str | None = None,
    ) -> str:
        """List available documents in the knowledge base.

        Returns document titles, source types, and timestamps.
        Optional source_type filter: markdown, google_doc, google_sheets, github.
        """
        return await _pam_list_documents(limit=limit, source_type=source_type)


async def _pam_get_document(
    document_title: str | None = None,
    source_id: str | None = None,
) -> str:
    """Implementation of pam_get_document."""
    from sqlalchemy import select

    from pam.common.models import Document, Segment

    services = get_services()

    async with services.session_factory() as session:
        stmt = select(Document)
        if document_title:
            stmt = stmt.where(Document.title.ilike(f"%{document_title}%"))
        elif source_id:
            stmt = stmt.where(Document.source_id == source_id)
        else:
            return json.dumps({"error": "Provide either document_title or source_id"})

        result = await session.execute(stmt)
        doc = result.scalars().first()

        if doc is None:
            return json.dumps({"error": f"Document not found: {document_title or source_id}"})

        seg_stmt = (
            select(Segment)
            .where(Segment.document_id == doc.id)
            .order_by(Segment.position)
        )
        seg_result = await session.execute(seg_stmt)
        segments = seg_result.scalars().all()

        return json.dumps(
            {
                "id": str(doc.id),
                "title": doc.title,
                "source_type": doc.source_type,
                "source_id": doc.source_id,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "segments": [
                    {
                        "content": seg.content,
                        "section_path": seg.section_path,
                        "position": seg.position,
                    }
                    for seg in segments
                ],
            },
            indent=2,
        )


async def _pam_list_documents(
    limit: int = 20,
    source_type: str | None = None,
) -> str:
    """Implementation of pam_list_documents."""
    from sqlalchemy import select

    from pam.common.models import Document

    services = get_services()

    async with services.session_factory() as session:
        stmt = select(Document).order_by(Document.updated_at.desc()).limit(limit)
        if source_type:
            stmt = stmt.where(Document.source_type == source_type)

        result = await session.execute(stmt)
        docs = result.scalars().all()

        return json.dumps(
            {
                "documents": [
                    {
                        "id": str(doc.id),
                        "title": doc.title,
                        "source_type": doc.source_type,
                        "created_at": doc.created_at.isoformat() if doc.created_at else None,
                        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                    }
                    for doc in docs
                ],
                "count": len(docs),
            },
            indent=2,
        )


def _register_graph_tools(mcp: FastMCP) -> None:
    """Register graph-related MCP tools."""

    @mcp.tool()
    async def pam_graph_search(
        query: str,
        entity_name: str | None = None,
    ) -> str:
        """Search the knowledge graph for entity relationships and connections.

        Use for questions about what entities relate to, depend on, or interact with.
        Examples: 'what depends on AuthService?', 'what is connected to payments?'
        """
        return await _pam_graph_search(query=query, entity_name=entity_name)

    @mcp.tool()
    async def pam_graph_neighbors(
        entity_name: str,
    ) -> str:
        """Explore the 1-hop neighborhood of an entity in the knowledge graph.

        Returns the entity and all directly connected entities with their relationships.
        """
        return await _pam_graph_neighbors(entity_name=entity_name)

    @mcp.tool()
    async def pam_entity_history(
        entity_name: str,
        since: str | None = None,
    ) -> str:
        """Get the temporal change history of a specific entity.

        Shows how an entity has changed over time. Optional 'since' parameter
        accepts ISO datetime (e.g. '2026-01-01T00:00:00Z') to filter changes.
        """
        return await _pam_entity_history(entity_name=entity_name, since=since)


async def _pam_graph_search(query: str, entity_name: str | None = None) -> str:
    """Implementation of pam_graph_search."""
    services = get_services()
    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    search_query = f"{entity_name}: {query}" if entity_name else query
    edges = await services.graph_service.client.search(query=search_query, num_results=10)

    return json.dumps(
        {
            "results": [
                {
                    "fact": getattr(edge, "fact", str(edge)),
                    "source_name": getattr(edge, "source_node_name", None),
                    "target_name": getattr(edge, "target_node_name", None),
                    "relation_type": getattr(edge, "name", None),
                }
                for edge in edges
            ],
            "count": len(edges),
        },
        indent=2,
    )


async def _pam_graph_neighbors(entity_name: str) -> str:
    """Implementation of pam_graph_neighbors."""
    services = get_services()
    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    query = f"relationships of {entity_name}"
    edges = await services.graph_service.client.search(query=query, num_results=20)

    neighbors: list[dict[str, Any]] = []
    for edge in edges:
        src = getattr(edge, "source_node_name", None)
        tgt = getattr(edge, "target_node_name", None)
        if src and tgt:
            neighbor_name = tgt if src.lower() == entity_name.lower() else src
            neighbors.append({
                "name": neighbor_name,
                "relationship": getattr(edge, "name", None),
                "fact": getattr(edge, "fact", str(edge)),
                "direction": "outgoing" if src.lower() == entity_name.lower() else "incoming",
            })

    return json.dumps(
        {"entity": entity_name, "neighbors": neighbors, "count": len(neighbors)},
        indent=2,
    )


async def _pam_entity_history(entity_name: str, since: str | None = None) -> str:
    """Implementation of pam_entity_history."""
    services = get_services()
    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    query = f"history of {entity_name}"
    edges = await services.graph_service.client.search(query=query, num_results=20)

    history = [
        {
            "fact": getattr(edge, "fact", str(edge)),
            "relation_type": getattr(edge, "name", None),
            "created_at": getattr(edge, "created_at", None),
        }
        for edge in edges
    ]

    if since:
        history = [h for h in history if h.get("created_at") and h["created_at"] >= since]

    return json.dumps(
        {"entity": entity_name, "history": history, "count": len(history)},
        indent=2,
    )


def _register_utility_tools(mcp: FastMCP) -> None:
    """Register utility MCP tools."""

    @mcp.tool()
    async def pam_query_data(
        sql: str | None = None,
        list_tables: bool = False,
    ) -> str:
        """Run SQL queries against registered data files (CSV, Parquet, JSON) via DuckDB.

        Set list_tables=true to see available tables and their schemas.
        Queries must be read-only SELECT statements. Max 1000 rows returned.
        """
        return await _pam_query_data(sql=sql, list_tables=list_tables)

    @mcp.tool()
    async def pam_ingest(
        folder_path: str,
        source_type: str = "markdown",
    ) -> str:
        """Trigger document ingestion from a local folder.

        Parses documents, chunks them, embeds, and stores in the knowledge base.
        source_type: markdown, google_doc, google_sheets, github.
        Returns a task ID for monitoring progress.
        """
        return await _pam_ingest(folder_path=folder_path, source_type=source_type)


async def _pam_query_data(sql: str | None = None, list_tables: bool = False) -> str:
    """Implementation of pam_query_data."""
    services = get_services()
    if services.duckdb_service is None:
        return json.dumps({"error": "DuckDB analytics is not configured (no DUCKDB_DATA_DIR set)"})

    if list_tables:
        tables = services.duckdb_service.list_tables()
        return json.dumps(tables, indent=2)

    if not sql:
        return json.dumps({"error": "Provide a SQL query or set list_tables=true"})

    result = services.duckdb_service.query(sql)
    return json.dumps(result, indent=2)


async def _pam_ingest(folder_path: str, source_type: str = "markdown") -> str:
    """Implementation of pam_ingest — triggers folder ingestion."""
    import uuid as uuid_mod

    from pam.ingestion import task_manager

    services = get_services()
    task_id = uuid_mod.uuid4()

    try:
        async with services.session_factory() as session:
            await task_manager.create_task(folder_path=folder_path, session=session)

        task_manager.spawn_ingestion_task(
            task_id=task_id,
            folder_path=folder_path,
            es_client=services.es_client,
            embedder=services.embedder,
            session_factory=services.session_factory,
            cache_service=services.cache_service,
            graph_service=services.graph_service,
            vdb_store=services.vdb_store,
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to start ingestion: {e}"})

    return json.dumps(
        {
            "task_id": str(task_id),
            "status": "started",
            "folder_path": folder_path,
            "source_type": source_type,
            "message": "Ingestion task started. Poll /api/ingest/tasks/{task_id} for progress.",
        },
        indent=2,
    )


def _register_resources(mcp: FastMCP) -> None:
    """Register MCP resources. Implemented in Task 8."""
    pass
