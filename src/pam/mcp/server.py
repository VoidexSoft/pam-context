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

    Raises RuntimeError if called before initialize().
    """
    if _services is None:
        msg = "MCP services not initialized — call initialize() first"
        raise RuntimeError(msg)
    return _services


def initialize(services: PamServices) -> None:
    """Set the global services instance. Called once at startup."""
    global _services
    _services = services


def create_mcp_server() -> FastMCP:
    """Create and return the FastMCP server with all tools registered."""
    mcp = FastMCP(
        "PAM Context",
        instructions=(
            "Business Knowledge Layer for LLMs — search documents, query knowledge graph, "
            "trigger ingestion, store and recall memories"
        ),
    )
    _register_search_tools(mcp)
    _register_document_tools(mcp)
    _register_graph_tools(mcp)
    _register_utility_tools(mcp)
    _register_memory_tools(mcp)
    _register_conversation_tools(mcp)
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
    embedding = (await services.embedder.embed_texts([query]))[0]
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
    embedding = (await services.embedder.embed_texts([query]))[0]

    # Normalize mode for routing (default to hybrid)
    m = (mode or "hybrid").lower()

    # Build concurrent tasks based on mode
    tasks: dict[str, Any] = {}
    # Documents (ES) always runs
    tasks["documents"] = services.search_service.search(
        query=query,
        query_embedding=embedding,
        top_k=5,
    )
    # Graph: skip for factual and entity modes
    if services.graph_service is not None and m not in ("factual", "entity"):
        tasks["graph"] = services.graph_service.client.search(query=query, num_results=5)
    if services.vdb_store is not None:
        # Entity VDB: skip for factual and conceptual modes
        if m not in ("factual", "conceptual"):
            tasks["entities"] = services.vdb_store.search_entities(
                query_embedding=embedding,
                top_k=5,
            )
        # Relationship VDB: skip for factual and entity modes
        if m not in ("factual", "entity"):
            tasks["relationships"] = services.vdb_store.search_relationships(
                query_embedding=embedding,
                top_k=5,
            )

    keys = list(tasks.keys())
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results_map: dict[str, Any] = {}
    for key, result in zip(keys, results_list, strict=False):
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

    graph_results = [
        {
            "fact": getattr(edge, "fact", str(edge)),
            "source_name": getattr(edge, "source_node_name", None),
            "target_name": getattr(edge, "target_node_name", None),
            "relation_type": getattr(edge, "name", None),
        }
        for edge in results_map.get("graph", [])
    ]

    entity_results = [
        {
            "name": hit.get("name", ""),
            "type": hit.get("entity_type", ""),
            "description": hit.get("description", ""),
            "score": hit.get("score", 0),
        }
        for hit in results_map.get("entities", [])
    ]

    rel_results = [
        {
            "src_entity": hit.get("src_entity", ""),
            "tgt_entity": hit.get("tgt_entity", ""),
            "rel_type": hit.get("rel_type", ""),
            "keywords": hit.get("keywords", ""),
            "score": hit.get("score", 0),
        }
        for hit in results_map.get("relationships", [])
    ]

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

        seg_stmt = select(Segment).where(Segment.document_id == doc.id).order_by(Segment.position)
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
        stmt = select(Document).order_by(Document.updated_at.desc())
        if source_type:
            stmt = stmt.where(Document.source_type == source_type)
        stmt = stmt.limit(limit)

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
            neighbors.append(
                {
                    "name": neighbor_name,
                    "relationship": getattr(edge, "name", None),
                    "fact": getattr(edge, "fact", str(edge)),
                    "direction": "outgoing" if src.lower() == entity_name.lower() else "incoming",
                }
            )

    return json.dumps(
        {"entity": entity_name, "neighbors": neighbors, "count": len(neighbors)},
        indent=2,
    )


async def _pam_entity_history(entity_name: str, since: str | None = None) -> str:
    """Implementation of pam_entity_history."""
    from datetime import datetime as _dt

    services = get_services()
    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    query = f"history of {entity_name}"
    edges = await services.graph_service.client.search(query=query, num_results=20)

    history = []
    for edge in edges:
        created_at = getattr(edge, "created_at", None)
        if isinstance(created_at, _dt):
            created_at = created_at.isoformat()
        history.append(
            {
                "fact": getattr(edge, "fact", str(edge)),
                "relation_type": getattr(edge, "name", None),
                "created_at": created_at,
            }
        )

    if since:
        since_normalized = since.replace("Z", "+00:00")
        history = [
            h for h in history if h.get("created_at") and h["created_at"].replace("Z", "+00:00") >= since_normalized
        ]

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
    ) -> str:
        """Trigger document ingestion from a local folder.

        Parses markdown documents, chunks them, embeds, and stores in the knowledge base.
        Returns a task ID for monitoring progress.
        """
        return await _pam_ingest(folder_path=folder_path)


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

    result = services.duckdb_service.execute_query(sql)
    return json.dumps(result, indent=2)


async def _pam_ingest(folder_path: str) -> str:
    """Implementation of pam_ingest — triggers folder ingestion."""
    from pathlib import Path

    from pam.common.config import get_settings
    from pam.ingestion import task_manager

    settings = get_settings()
    if not settings.ingest_root:
        return json.dumps({"error": "Ingestion root not configured (set INGEST_ROOT)"})
    root = Path(settings.ingest_root).resolve()
    folder = Path(folder_path).resolve()
    if not folder.is_relative_to(root):
        return json.dumps({"error": "Path outside allowed ingestion root"})
    if not folder.is_dir():
        return json.dumps({"error": f"Directory not found: {folder_path}"})

    services = get_services()

    try:
        async with services.session_factory() as session:
            task = await task_manager.create_task(folder_path=folder_path, session=session)

        task_manager.spawn_ingestion_task(
            task_id=task.id,
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
            "task_id": str(task.id),
            "status": "started",
            "folder_path": folder_path,
            "message": f"Ingestion task started. Poll /api/ingest/tasks/{task.id} for progress.",
        },
        indent=2,
    )


def _register_memory_tools(mcp: FastMCP) -> None:
    """Register memory CRUD MCP tools."""

    @mcp.tool()
    async def pam_remember(
        content: str,
        memory_type: str = "fact",
        source: str | None = None,
        importance: float = 0.5,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """Store a fact, preference, or observation in PAM's memory.

        Automatically deduplicates — if a similar memory already exists
        (cosine similarity > 0.9), the content is merged instead of duplicated.

        memory_type: fact, preference, observation, or conversation_summary.
        importance: 0.0 to 1.0 (default 0.5). Higher = more prominent in recall.
        """
        return await _pam_remember(
            content=content,
            memory_type=memory_type,
            source=source,
            importance=importance,
            user_id=user_id,
            project_id=project_id,
        )

    @mcp.tool()
    async def pam_recall(
        query: str,
        top_k: int = 10,
        user_id: str | None = None,
        project_id: str | None = None,
        memory_type: str | None = None,
    ) -> str:
        """Recall relevant memories from PAM's memory store.

        Searches by semantic similarity to the query. Returns memories
        ranked by relevance score.
        """
        return await _pam_recall(
            query=query,
            top_k=top_k,
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
        )

    @mcp.tool()
    async def pam_forget(
        memory_id: str,
        user_id: str,
    ) -> str:
        """Delete a specific memory from PAM's memory store.

        Permanently removes the memory from both PostgreSQL and the
        search index. Use pam_recall first to find the memory_id.
        Requires user_id to verify ownership before deletion.
        """
        return await _pam_forget(memory_id=memory_id, user_id=user_id)


async def _pam_remember(
    content: str,
    memory_type: str = "fact",
    source: str | None = None,
    importance: float = 0.5,
    user_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Implementation of pam_remember."""
    import uuid as uuid_mod

    services = get_services()

    if services.memory_service is None:
        return json.dumps({"error": "Memory service is unavailable"})

    try:
        parsed_user_id = uuid_mod.UUID(user_id) if user_id else None
        parsed_project_id = uuid_mod.UUID(project_id) if project_id else None
    except ValueError:
        return json.dumps({"error": f"Invalid user_id or project_id: {user_id}, {project_id}"})

    # Clamp importance to valid range (REST path uses Pydantic ge=0.0, le=1.0)
    importance = max(0.0, min(1.0, importance))

    try:
        result = await services.memory_service.store(
            content=content,
            memory_type=memory_type,
            source=source or "mcp",
            importance=importance,
            user_id=parsed_user_id,
            project_id=parsed_project_id,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps(
        {
            "id": str(result.id),
            "content": result.content,
            "type": result.type,
            "importance": result.importance,
            "created_at": result.created_at.isoformat() if result.created_at else None,
        },
        indent=2,
    )


async def _pam_recall(
    query: str,
    top_k: int = 10,
    user_id: str | None = None,
    project_id: str | None = None,
    memory_type: str | None = None,
) -> str:
    """Implementation of pam_recall."""
    import uuid as uuid_mod

    services = get_services()

    if services.memory_service is None:
        return json.dumps({"error": "Memory service is unavailable"})

    try:
        parsed_user_id = uuid_mod.UUID(user_id) if user_id else None
        parsed_project_id = uuid_mod.UUID(project_id) if project_id else None
    except ValueError:
        return json.dumps({"error": f"Invalid user_id or project_id: {user_id}, {project_id}"})

    results = await services.memory_service.search(
        query=query,
        user_id=parsed_user_id,
        project_id=parsed_project_id,
        type_filter=memory_type,
        top_k=top_k,
    )

    return json.dumps(
        {
            "memories": [
                {
                    "id": str(r.memory.id),
                    "content": r.memory.content,
                    "type": r.memory.type,
                    "importance": r.memory.importance,
                    "score": r.score,
                    "access_count": r.memory.access_count,
                    "created_at": r.memory.created_at.isoformat() if r.memory.created_at else None,
                }
                for r in results
            ],
            "count": len(results),
        },
        indent=2,
    )


async def _pam_forget(memory_id: str, user_id: str) -> str:
    """Implementation of pam_forget."""
    import uuid as uuid_mod

    services = get_services()

    if services.memory_service is None:
        return json.dumps({"error": "Memory service is unavailable"})

    try:
        mid = uuid_mod.UUID(memory_id)
        parsed_user_id = uuid_mod.UUID(user_id)
    except ValueError:
        return json.dumps({"error": f"Invalid memory_id or user_id: {memory_id}, {user_id}"})

    # Always verify ownership before deleting
    existing = await services.memory_service.get_for_ownership_check(mid)
    if existing is None:
        return json.dumps({"deleted": False, "memory_id": memory_id, "error": "Memory not found"})
    if existing.user_id != parsed_user_id:
        return json.dumps({"deleted": False, "memory_id": memory_id, "error": "Memory not found"})

    deleted = await services.memory_service.delete(mid)

    if deleted:
        return json.dumps({"deleted": True, "memory_id": memory_id})
    return json.dumps({"deleted": False, "memory_id": memory_id, "error": "Memory not found"})


def _register_conversation_tools(mcp: FastMCP) -> None:
    """Register conversation MCP tools."""

    @mcp.tool()
    async def pam_save_conversation(
        messages: list[dict],
        title: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """Save a conversation (list of messages) to PAM.

        Each message must have 'role' and 'content' keys.
        Returns the conversation_id and number of messages saved.
        """
        return await _pam_save_conversation(
            messages=messages,
            title=title,
            user_id=user_id,
            project_id=project_id,
        )

    @mcp.tool()
    async def pam_get_conversation_context(
        conversation_id: str,
        max_tokens: int = 2000,
    ) -> str:
        """Get recent conversation context formatted for LLM consumption.

        Returns the conversation as 'role: content' lines, truncated to
        max_tokens from the most recent messages backwards.
        """
        return await _pam_get_conversation_context(
            conversation_id=conversation_id,
            max_tokens=max_tokens,
        )


async def _pam_save_conversation(
    messages: list[dict],
    title: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Save a conversation to PAM."""
    import uuid as uuid_mod

    svc = get_services().conversation_service
    if svc is None:
        return json.dumps({"error": "ConversationService not available"})

    try:
        uid = uuid_mod.UUID(user_id) if user_id else None
        pid = uuid_mod.UUID(project_id) if project_id else None
    except ValueError:
        return json.dumps({"error": f"Invalid user_id or project_id: {user_id}, {project_id}"})

    # Validate message structure and role values before creating the conversation
    valid_roles = {"user", "assistant", "system"}
    for i, msg in enumerate(messages):
        if "role" not in msg or "content" not in msg:
            return json.dumps({"error": f"Message at index {i} missing required 'role' or 'content' key"})
        if msg["role"] not in valid_roles:
            return json.dumps(
                {
                    "error": f"Message at index {i} has invalid role '{msg['role']}'. "
                    f"Must be one of: {sorted(valid_roles)}",
                }
            )

    conv = await svc.create(user_id=uid, project_id=pid, title=title)

    try:
        for msg in messages:
            await svc.add_message(
                conversation_id=conv.id,
                role=msg["role"],
                content=msg["content"],
                metadata=msg.get("metadata", {}),
            )
    except Exception as exc:
        # Clean up the orphaned conversation record on failure, then return a
        # JSON error payload. MCP tools must return a string — never raise —
        # so the client receives a structured error instead of a transport crash.
        try:
            await svc.delete(conv.id)
        except Exception:
            logger.warning(
                "pam_save_conversation_orphan_cleanup_failed",
                conversation_id=str(conv.id),
                exc_info=True,
            )
        return json.dumps({"error": f"Failed to save conversation: {exc}"})

    return json.dumps(
        {
            "conversation_id": str(conv.id),
            "messages_saved": len(messages),
            "title": conv.title,
        }
    )


async def _pam_get_conversation_context(
    conversation_id: str,
    max_tokens: int = 2000,
) -> str:
    """Get recent conversation context."""
    import uuid as uuid_mod

    svc = get_services().conversation_service
    if svc is None:
        return json.dumps({"error": "ConversationService not available"})

    try:
        conv_id = uuid_mod.UUID(conversation_id)
    except ValueError:
        return json.dumps({"error": f"Invalid conversation_id: {conversation_id}"})

    context = await svc.get_recent_context(conv_id, max_tokens=max_tokens)
    return json.dumps({"conversation_id": conversation_id, "context": context})


def _register_resources(mcp: FastMCP) -> None:
    """Register MCP resources for system introspection."""

    @mcp.resource("pam://stats")
    async def stats_resource() -> str:
        """System statistics — document count, segment count, graph status."""
        return await _get_stats()

    @mcp.resource("pam://entities/{entity_type}")
    async def entities_resource(entity_type: str) -> str:
        """List entities of a given type from the entity VDB index."""
        return await _get_entities(entity_type=entity_type)

    @mcp.resource("pam://entities")
    async def all_entities_resource() -> str:
        """List all entities from the entity VDB index."""
        return await _get_entities(entity_type=None)


async def _get_stats() -> str:
    """Implementation of pam://stats resource."""
    from sqlalchemy import func, select

    from pam.common.config import get_settings
    from pam.common.models import Document

    services = get_services()
    settings = get_settings()

    stats: dict[str, Any] = {}

    async with services.session_factory() as session:
        result = await session.execute(select(func.count(Document.id)))
        stats["document_count"] = result.scalar() or 0

    try:
        es_count = await services.es_client.count(index=settings.elasticsearch_index)
        stats["segment_count"] = es_count.get("count", 0)
    except Exception:
        logger.warning("es_segment_count_failed", exc_info=True)
        stats["segment_count"] = "unavailable"

    stats["graph_available"] = services.graph_service is not None
    stats["duckdb_available"] = services.duckdb_service is not None

    return json.dumps(stats, indent=2)


async def _get_entities(entity_type: str | None = None) -> str:
    """Implementation of pam://entities resource."""
    from pam.common.config import get_settings

    services = get_services()
    settings = get_settings()

    if services.vdb_store is None:
        return json.dumps({"entities": [], "error": "Entity VDB not available"})

    body: dict[str, Any] = {"size": 100}
    if entity_type:
        body["query"] = {"term": {"entity_type": entity_type}}
    else:
        body["query"] = {"match_all": {}}

    try:
        result = await services.es_client.search(
            index=settings.entity_index,
            body=body,
        )
        entities = [
            {
                "name": hit["_source"].get("name", ""),
                "type": hit["_source"].get("entity_type", ""),
                "description": hit["_source"].get("description", ""),
            }
            for hit in result["hits"]["hits"]
        ]
        return json.dumps(
            {"entities": entities, "count": result["hits"]["total"]["value"]},
            indent=2,
        )
    except Exception as e:
        logger.warning("entity_resource_failed", exc_info=True)
        return json.dumps({"entities": [], "error": str(e)})
