"""Graph routes -- Neo4j / Graphiti status, neighborhood, and entity listing."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pam.api.deps import get_graph_service
from pam.api.pagination import decode_cursor, encode_cursor
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


@router.get("/graph/status")
async def graph_status(
    graph_service: GraphitiService = Depends(get_graph_service),
):
    """Return Neo4j connection status, entity counts, and last sync time.

    Always returns HTTP 200 -- the ``status`` field indicates whether the
    graph database is reachable (``connected`` vs ``disconnected``).
    """
    try:
        async with graph_service.client.driver.session() as session:
            # Entity counts by label
            result = await session.run(
                "MATCH (n:Entity) RETURN labels(n) AS labels, count(n) AS count"
            )
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
            result = await session.run(
                "MATCH (e:Episodic) RETURN max(e.created_at) AS last_sync"
            )
            sync_record = await result.single()
            last_sync_time = None
            if sync_record and sync_record["last_sync"]:
                last_sync_time = str(sync_record["last_sync"])

        return {
            "status": "connected",
            "entity_counts": entity_counts,
            "total_entities": total_entities,
            "last_sync_time": last_sync_time,
        }
    except Exception as exc:
        logger.warning("graph_status_failed", error=str(exc))
        return {"status": "disconnected", "error": str(exc)}


def _extract_entity_type(labels: list[str]) -> str:
    """Return the first non-'Entity' label, or 'Entity' as fallback."""
    for label in labels:
        if label != "Entity":
            return label
    return "Entity"


@router.get("/graph/neighborhood/{entity_name}", response_model=NeighborhoodResponse)
async def graph_neighborhood(
    entity_name: str,
    graph_service: GraphitiService = Depends(get_graph_service),
) -> NeighborhoodResponse:
    """Return 1-hop subgraph for a named entity.

    Returns the center node, its immediate neighbors, and the edges
    connecting them.  Edges are capped at 20.  Returns 404 if the
    entity is not found and 503 if Neo4j is unreachable.
    """
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
                        invalid_at=(
                            str(record["e_invalid"]) if record["e_invalid"] else None
                        ),
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
    # Validate entity_type against known taxonomy to prevent Cypher injection
    if entity_type and entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown entity type: {entity_type}. "
                f"Valid types: {', '.join(sorted(ENTITY_TYPES.keys()))}"
            ),
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
