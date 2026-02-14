"""Graph API routes — entity listing, subgraph, and timeline endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from pam.api.auth import get_current_user
from pam.api.deps import get_graph_client
from pam.common.graph import GraphClient
from pam.common.models import User

router = APIRouter(prefix="/graph", tags=["graph"])


def _require_graph(request: Request) -> GraphClient:
    client = get_graph_client(request)
    if client is None:
        raise HTTPException(status_code=503, detail="Knowledge graph not available")
    return client


@router.get("/entities")
async def list_entities(
    request: Request,
    label: str | None = Query(None, description="Filter by node label (Metric, Event, KPI, etc.)"),
    limit: int = Query(50, ge=1, le=200),
    _user: User | None = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List entities in the knowledge graph."""
    client = _require_graph(request)

    label_clause = f":{label}" if label else ""
    query = f"""
    MATCH (n{label_clause})
    WHERE n.name IS NOT NULL
    OPTIONAL MATCH (n)-[r]-()
    WITH n, labels(n)[0] AS label, count(r) AS rel_count
    RETURN n.name AS name, label, rel_count,
           n.version AS version, n.entity_type AS entity_type
    ORDER BY rel_count DESC, n.name
    LIMIT $limit
    """
    return await client.execute_read(query, {"limit": limit})


@router.get("/entity/{name}")
async def get_entity(
    name: str,
    request: Request,
    _user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Get entity details with all relationships."""
    client = _require_graph(request)

    # Get the entity node
    node_query = """
    MATCH (n {name: $name})
    RETURN n, labels(n)[0] AS label
    LIMIT 1
    """
    nodes = await client.execute_read(node_query, {"name": name})
    if not nodes:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found")

    node_data = nodes[0]

    # Get all relationships
    rel_query = """
    MATCH (n {name: $name})-[r]->(target)
    RETURN type(r) AS rel_type, target.name AS target_name,
           labels(target)[0] AS target_label, r.confidence AS confidence,
           r.valid_from AS valid_from, r.valid_to AS valid_to,
           'outgoing' AS direction
    UNION
    MATCH (source)-[r]->(n {name: $name})
    RETURN type(r) AS rel_type, source.name AS target_name,
           labels(source)[0] AS target_label, r.confidence AS confidence,
           r.valid_from AS valid_from, r.valid_to AS valid_to,
           'incoming' AS direction
    """
    relationships = await client.execute_read(rel_query, {"name": name})

    # Extract properties from node (filter out internal Neo4j ones)
    props = node_data.get("n", {}) if isinstance(node_data.get("n"), dict) else {}

    return {
        "name": name,
        "label": node_data.get("label", "Unknown"),
        "properties": props,
        "relationships": relationships,
    }


@router.get("/subgraph")
async def get_subgraph(
    request: Request,
    entity_name: str = Query(..., description="Center entity name"),
    depth: int = Query(2, ge=1, le=4, description="Max traversal depth"),
    _user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Get subgraph around an entity for visualization.

    Returns nodes and edges suitable for a force-directed graph.
    """
    client = _require_graph(request)

    query = f"""
    MATCH path = (start {{name: $name}})-[*1..{min(depth, 4)}]-(related)
    WHERE start <> related
    UNWIND relationships(path) AS rel
    WITH DISTINCT startNode(rel) AS from_node, rel, endNode(rel) AS to_node
    RETURN
        from_node.name AS source_name,
        labels(from_node)[0] AS source_label,
        type(rel) AS rel_type,
        to_node.name AS target_name,
        labels(to_node)[0] AS target_label,
        rel.confidence AS confidence
    LIMIT 200
    """
    edges_raw = await client.execute_read(query, {"name": entity_name})

    # Build nodes and edges for the graph
    nodes_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for edge in edges_raw:
        src = edge["source_name"]
        tgt = edge["target_name"]

        if src and src not in nodes_map:
            nodes_map[src] = {
                "id": src,
                "label": edge["source_label"],
                "isCenter": src == entity_name,
            }
        if tgt and tgt not in nodes_map:
            nodes_map[tgt] = {
                "id": tgt,
                "label": edge["target_label"],
                "isCenter": tgt == entity_name,
            }

        edges.append({
            "source": src,
            "target": tgt,
            "rel_type": edge["rel_type"],
            "confidence": edge.get("confidence"),
        })

    # If no edges found but entity exists, return it as a single node
    if not nodes_map:
        check = await client.execute_read(
            "MATCH (n {name: $name}) RETURN n.name AS name, labels(n)[0] AS label LIMIT 1",
            {"name": entity_name},
        )
        if check:
            nodes_map[entity_name] = {
                "id": entity_name,
                "label": check[0].get("label", "Unknown"),
                "isCenter": True,
            }
        else:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' not found")

    return {
        "nodes": list(nodes_map.values()),
        "edges": edges,
        "center": entity_name,
    }


@router.get("/timeline/{entity_name}")
async def get_timeline(
    entity_name: str,
    request: Request,
    since: str | None = Query(None, description="ISO date filter (e.g. 2026-01-01)"),
    _user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Get temporal history of an entity's relationships."""
    client = _require_graph(request)

    params: dict[str, Any] = {"name": entity_name}
    since_clause = ""
    if since:
        since_clause = "AND r.valid_from >= $since"
        params["since"] = since

    query = f"""
    MATCH (n {{name: $name}})-[r]->(target)
    WHERE r.valid_from IS NOT NULL {since_clause}
    RETURN type(r) AS rel_type,
           target.name AS target_name,
           labels(target)[0] AS target_label,
           r.valid_from AS valid_from,
           r.valid_to AS valid_to,
           r.confidence AS confidence
    ORDER BY r.valid_from DESC
    LIMIT 100
    """
    params["limit"] = 100
    history = await client.execute_read(query, params)

    # Get entity metadata
    meta_query = """
    MATCH (n {name: $name})
    RETURN labels(n)[0] AS label, n.version AS version
    LIMIT 1
    """
    meta = await client.execute_read(meta_query, {"name": entity_name})

    return {
        "entity_name": entity_name,
        "label": meta[0].get("label") if meta else "Unknown",
        "version": meta[0].get("version") if meta else None,
        "history": history,
    }
