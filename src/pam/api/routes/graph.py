"""Graph routes -- Neo4j / Graphiti status, neighborhood, and entity listing."""

from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.deps import get_db, get_graph_service
from pam.api.pagination import decode_cursor, encode_cursor
from pam.common.models import Document, SyncLog
from pam.graph.entity_types import ENTITY_TYPES
from pam.graph.service import GraphitiService

logger = structlog.get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    """A node in the graph response."""

    uuid: str
    name: str
    entity_type: str  # Label with "Entity" filtered out
    summary: str | None = None


class GraphEdge(BaseModel):
    """An edge in the graph response."""

    uuid: str
    source_name: str
    target_name: str
    relationship_type: str
    fact: str
    valid_at: str | None = None
    invalid_at: str | None = None


class NeighborhoodResponse(BaseModel):
    """1-hop neighborhood subgraph for an entity."""

    center: GraphNode
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_edges: int  # Total before any limit


class EntityListItem(BaseModel):
    """An entity in the listing."""

    uuid: str
    name: str
    entity_type: str
    summary: str | None = None


class EntityListResponse(BaseModel):
    """Paginated list of entities."""

    entities: list[EntityListItem]
    next_cursor: str | None = None


class EntityHistoryResponse(BaseModel):
    """All edges (including invalidated) for a single entity, ordered by valid_at."""

    entity: GraphNode
    edges: list[GraphEdge]


class SyncLogResponse(BaseModel):
    """A sync log entry with diff details."""

    id: str
    document_id: str | None = None
    action: str
    segments_affected: int | None = None
    details: dict
    created_at: str


@router.get("/graph/status")
async def graph_status(
    db: AsyncSession = Depends(get_db),
    graph_service: GraphitiService = Depends(get_graph_service),
):
    """Return Neo4j connection status, entity counts, and last sync time.

    Always returns HTTP 200 -- the ``status`` field indicates whether the
    graph database is reachable (``connected`` vs ``disconnected`` vs
    ``unavailable``).  PG document counts are always included regardless
    of Neo4j availability.
    """
    # Always query PG for document counts (works even without Neo4j)
    total_doc_result = await db.execute(select(func.count()).select_from(Document))
    document_count = total_doc_result.scalar() or 0
    synced_result = await db.execute(
        select(func.count()).select_from(Document).where(Document.graph_synced == True)  # noqa: E712
    )
    graph_synced_count = synced_result.scalar() or 0

    # Null guard: graph_service was never created at startup
    if graph_service is None:
        return {
            "status": "unavailable",
            "entity_counts": {},
            "total_entities": 0,
            "last_sync_time": None,
            "document_count": document_count,
            "graph_synced_count": graph_synced_count,
        }

    try:
        async with graph_service.client.driver.session() as session:
            # Entity counts by label
            result = await session.run("MATCH (n:Entity) RETURN labels(n) AS labels, count(n) AS count")
            records = await result.data()
            entity_counts: dict[str, int] = {}
            total_entities = 0
            for record in records:
                count = record["count"]
                total_entities += count
                for label in record["labels"]:
                    if label != "Entity":
                        entity_counts[label] = entity_counts.get(label, 0) + count

            # Last sync time
            result = await session.run("MATCH (e:Episodic) RETURN max(e.created_at) AS last_sync")
            sync_record = await result.single()
            last_sync_time = None
            if sync_record and sync_record["last_sync"]:
                last_sync_time = str(sync_record["last_sync"])

        return {
            "status": "connected",
            "entity_counts": entity_counts,
            "total_entities": total_entities,
            "last_sync_time": last_sync_time,
            "document_count": document_count,
            "graph_synced_count": graph_synced_count,
        }
    except Exception as exc:
        logger.warning("graph_status_failed", error=str(exc))
        return {
            "status": "disconnected",
            "error": str(exc),
            "document_count": document_count,
            "graph_synced_count": graph_synced_count,
        }


def _extract_entity_type(labels: list[str]) -> str:
    """Return the first non-'Entity' label, or 'Entity' as fallback."""
    for label in labels:
        if label != "Entity":
            return label
    return "Entity"


@router.get("/graph/neighborhood/{entity_name:path}", response_model=NeighborhoodResponse)
async def graph_neighborhood(
    entity_name: str,
    graph_service: GraphitiService = Depends(get_graph_service),
) -> NeighborhoodResponse:
    """Return 1-hop subgraph for a named entity.

    Returns the center node, its immediate neighbors, and the edges
    connecting them.  Edges are capped at 20.  Returns 404 if the
    entity is not found and 503 if Neo4j is unreachable.
    """
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    try:
        async with graph_service.client.driver.session() as session:
            result = await session.run(
                """
                MATCH (n:Entity)
                WHERE n.name =~ $name_pattern
                WITH n LIMIT 1
                OPTIONAL MATCH (n)-[e:RELATES_TO]-(m:Entity)
                WHERE e.invalid_at IS NULL
                RETURN n.uuid AS n_uuid, n.name AS n_name,
                       labels(n) AS n_labels, n.summary AS n_summary,
                       e.uuid AS e_uuid, e.fact AS e_fact, e.name AS e_name,
                       e.valid_at AS e_valid, e.invalid_at AS e_invalid,
                       startNode(e).name AS e_source, endNode(e).name AS e_target,
                       m.uuid AS m_uuid, m.name AS m_name,
                       labels(m) AS m_labels, m.summary AS m_summary
                ORDER BY e.valid_at DESC
                LIMIT 21
                """,
                name_pattern=f"(?i){entity_name}",
            )
            records = await result.data()

        if not records or records[0]["n_uuid"] is None:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{entity_name}' not found",
            )

        # Center node from the first record
        first = records[0]
        center = GraphNode(
            uuid=first["n_uuid"],
            name=first["n_name"],
            entity_type=_extract_entity_type(first["n_labels"]),
            summary=first["n_summary"],
        )

        # Build unique neighbor nodes and edges (dedup by uuid)
        seen_nodes: set[str] = set()
        seen_edges: set[str] = set()
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        for record in records:
            # Skip records where the OPTIONAL MATCH produced no edge
            if record["e_uuid"] is None:
                continue

            e_uuid = record["e_uuid"]
            if e_uuid not in seen_edges:
                seen_edges.add(e_uuid)
                edges.append(
                    GraphEdge(
                        uuid=e_uuid,
                        source_name=record["e_source"],
                        target_name=record["e_target"],
                        relationship_type=record["e_name"] or "",
                        fact=record["e_fact"] or "",
                        valid_at=str(record["e_valid"]) if record["e_valid"] else None,
                        invalid_at=(str(record["e_invalid"]) if record["e_invalid"] else None),
                    )
                )

            m_uuid = record["m_uuid"]
            if m_uuid and m_uuid not in seen_nodes:
                seen_nodes.add(m_uuid)
                nodes.append(
                    GraphNode(
                        uuid=m_uuid,
                        name=record["m_name"],
                        entity_type=_extract_entity_type(record["m_labels"]),
                        summary=record["m_summary"],
                    )
                )

        total_edges = len(edges)
        # Cap at 20 edges per GRAPH-06
        edges = edges[:20]
        nodes_in_edges = {e.source_name for e in edges} | {e.target_name for e in edges}
        nodes = [n for n in nodes if n.name in nodes_in_edges]

        return NeighborhoodResponse(
            center=center,
            nodes=nodes,
            edges=edges,
            total_edges=total_edges,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("graph_neighborhood_failed", entity=entity_name, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Graph database unavailable",
        ) from exc


_MAX_ENTITIES_PER_PAGE = 50


@router.get("/graph/entities", response_model=EntityListResponse)
async def graph_entities(
    entity_type: str | None = None,
    limit: int = _MAX_ENTITIES_PER_PAGE,
    cursor: str | None = None,
    graph_service: GraphitiService = Depends(get_graph_service),
) -> EntityListResponse:
    """List entity nodes with optional type filter and cursor pagination.

    Query params:
      - ``entity_type``: Optional label to filter by (must be in ENTITY_TYPES taxonomy).
      - ``limit``: Page size, capped at 50.
      - ``cursor``: Opaque cursor from a previous response's ``next_cursor``.

    Returns 400 for unknown entity types and 503 if Neo4j is unreachable.
    """
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    # Validate entity_type against known taxonomy to prevent Cypher injection
    if entity_type and entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(f"Unknown entity type: {entity_type}. Valid types: {', '.join(sorted(ENTITY_TYPES.keys()))}"),
        )

    effective_limit = min(limit, _MAX_ENTITIES_PER_PAGE)

    # Decode cursor to get the last UUID from the previous page
    cursor_uuid: str | None = None
    if cursor:
        try:
            cursor_data = decode_cursor(cursor)
            cursor_uuid = cursor_data["id"]
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor") from None

    try:
        async with graph_service.client.driver.session() as session:
            # Build Cypher dynamically
            cypher = "MATCH (n:Entity) "
            params: dict[str, object] = {"limit": effective_limit + 1}

            where_parts: list[str] = []
            if cursor_uuid:
                where_parts.append("n.uuid < $cursor_uuid")
                params["cursor_uuid"] = cursor_uuid

            # entity_type is validated above; label matching uses Cypher syntax
            if entity_type:
                label_clause = f"n:{entity_type}"
                if where_parts:
                    cypher += f"WHERE {label_clause} AND " + " AND ".join(where_parts) + " "
                else:
                    cypher += f"WHERE {label_clause} "
            elif where_parts:
                cypher += "WHERE " + " AND ".join(where_parts) + " "

            cypher += (
                "RETURN labels(n) AS labels, n.name AS name, "
                "n.uuid AS uuid, n.summary AS summary "
                "ORDER BY n.uuid DESC LIMIT $limit"
            )

            result = await session.run(cypher, **params)
            records = await result.data()

        # Detect next page
        has_next = len(records) > effective_limit
        items = records[:effective_limit]

        entities = [
            EntityListItem(
                uuid=r["uuid"],
                name=r["name"],
                entity_type=_extract_entity_type(r["labels"]),
                summary=r["summary"],
            )
            for r in items
        ]

        next_cursor: str | None = None
        if has_next and items:
            last_uuid = items[-1]["uuid"]
            next_cursor = encode_cursor(last_uuid, last_uuid)

        return EntityListResponse(entities=entities, next_cursor=next_cursor)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("graph_entities_failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Graph database unavailable",
        ) from exc


@router.get(
    "/graph/entity/{entity_name:path}/history",
    response_model=EntityHistoryResponse,
)
async def entity_history(
    entity_name: str,
    graph_service: GraphitiService = Depends(get_graph_service),
) -> EntityHistoryResponse:
    """Return all edges (including invalidated) for a named entity.

    Edges are ordered by ``valid_at ASC`` so callers can render a temporal
    timeline.  Returns 404 if the entity is not found and 503 if Neo4j
    is unreachable.
    """
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service unavailable")

    try:
        escaped_name = re.escape(entity_name)
        async with graph_service.client.driver.session() as session:
            result = await session.run(
                """
                MATCH (n:Entity)
                WHERE n.name =~ $name_pattern
                WITH n LIMIT 1
                OPTIONAL MATCH (n)-[e:RELATES_TO]-(m:Entity)
                RETURN n.uuid AS n_uuid, n.name AS n_name,
                       labels(n) AS n_labels, n.summary AS n_summary,
                       e.uuid AS e_uuid, e.fact AS e_fact, e.name AS e_name,
                       e.valid_at AS e_valid, e.invalid_at AS e_invalid,
                       startNode(e).name AS e_source, endNode(e).name AS e_target
                ORDER BY e.valid_at ASC
                LIMIT 50
                """,
                name_pattern=f"(?i){escaped_name}",
            )
            records = await result.data()

        if not records or records[0]["n_uuid"] is None:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{entity_name}' not found",
            )

        first = records[0]
        entity = GraphNode(
            uuid=first["n_uuid"],
            name=first["n_name"],
            entity_type=_extract_entity_type(first["n_labels"]),
            summary=first["n_summary"],
        )

        seen_edges: set[str] = set()
        edges: list[GraphEdge] = []
        for record in records:
            if record["e_uuid"] is None:
                continue
            e_uuid = record["e_uuid"]
            if e_uuid not in seen_edges:
                seen_edges.add(e_uuid)
                edges.append(
                    GraphEdge(
                        uuid=e_uuid,
                        source_name=record["e_source"],
                        target_name=record["e_target"],
                        relationship_type=record["e_name"] or "",
                        fact=record["e_fact"] or "",
                        valid_at=str(record["e_valid"]) if record["e_valid"] else None,
                        invalid_at=(str(record["e_invalid"]) if record["e_invalid"] else None),
                    )
                )

        return EntityHistoryResponse(entity=entity, edges=edges)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("entity_history_failed", entity=entity_name, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Graph database unavailable",
        ) from exc


_MAX_SYNC_LOGS = 50


@router.get("/graph/sync-logs", response_model=list[SyncLogResponse])
async def graph_sync_logs(
    document_id: str | None = Query(default=None),
    limit: int = Query(default=10),
    db: AsyncSession = Depends(get_db),
) -> list[SyncLogResponse]:
    """Return recent sync-log entries with diff details.

    Optionally filter by ``document_id``.  Limit capped at 50.
    """
    effective_limit = min(limit, _MAX_SYNC_LOGS)
    try:
        stmt = select(SyncLog).order_by(SyncLog.created_at.desc()).limit(effective_limit)
        if document_id:
            stmt = stmt.where(SyncLog.document_id == document_id)

        result = await db.execute(stmt)
        rows = result.scalars().all()

        return [
            SyncLogResponse(
                id=str(row.id),
                document_id=str(row.document_id) if row.document_id else None,
                action=row.action,
                segments_affected=row.segments_affected,
                details=row.details or {},
                created_at=row.created_at.isoformat() if row.created_at else "",
            )
            for row in rows
        ]
    except Exception as exc:
        logger.warning("graph_sync_logs_failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc
