"""Graph query functions for agent tools.

Provides search_graph_relationships (semantic edge search via Graphiti) and
get_entity_history (temporal edge history via direct Cypher).  Both functions
return formatted text strings with source document citations extracted from
episode metadata.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pam.graph.service import GraphitiService

logger = structlog.get_logger()

MAX_EDGES = 20
MAX_CHARS = 3000


def _parse_source_description(source_desc: str | None) -> str | None:
    """Extract document title from episode source_description.

    Expected format: "Document: {title} | Source: {source_id} | Chunk: {position}"
    Returns the title, or None if parsing fails.
    """
    if not source_desc:
        return None
    match = re.match(r"Document:\s*(.+?)\s*\|", source_desc)
    return match.group(1).strip() if match else None


def _truncate(text: str, total: int) -> str:
    """Truncate text to MAX_CHARS with a summary suffix."""
    if len(text) <= MAX_CHARS:
        return text
    return (
        text[: MAX_CHARS - 100]
        + f"\n\n... truncated. {total} total relationships found."
        " Ask to narrow by type or relationship."
    )


async def search_graph_relationships(
    graph_service: GraphitiService,
    query: str,
    entity_name: str | None = None,
    relationship_type: str | None = None,
) -> str:
    """Search the knowledge graph for entity relationships using Graphiti hybrid search.

    Uses Graphiti's search() for BM25+vector edge search, then filters by
    entity_name and relationship_type if provided.  Extracts source document
    names from episode metadata for citation.

    Returns a formatted text string suitable for an agent tool result.
    """
    logger.info(
        "graph_search_relationships",
        query=query,
        entity_name=entity_name,
        relationship_type=relationship_type,
    )

    try:
        edges = await graph_service.client.search(
            query=query,
            num_results=MAX_EDGES,
        )
    except Exception:
        logger.warning("graph_search_failed", exc_info=True)
        return "Graph database is currently unavailable. Try search_knowledge instead."

    # Apply optional filters
    if entity_name:
        name_lower = entity_name.lower()
        edges = [edge for edge in edges if name_lower in edge.fact.lower()]

    if relationship_type:
        rel_lower = relationship_type.lower()
        edges = [e for e in edges if rel_lower in e.name.lower()]

    if not edges:
        if entity_name:
            return (
                f"No relationships found for '{entity_name}' in the knowledge graph."
                " Searching documents may help."
            )
        return "No relevant relationships found in the knowledge graph."

    # Cap at MAX_EDGES
    edges = edges[:MAX_EDGES]
    total_count = len(edges)

    # Gather episode UUIDs for source document extraction
    all_episode_uuids: list[str] = []
    for edge in edges:
        if edge.episodes:
            all_episode_uuids.extend(edge.episodes)
    all_episode_uuids = list(set(all_episode_uuids))

    # Query episodes for source_description
    episode_sources: dict[str, str | None] = {}
    if all_episode_uuids:
        try:
            result = await graph_service.client.driver.execute_query(
                "MATCH (ep:Episodic) WHERE ep.uuid IN $uuids "
                "RETURN ep.uuid AS uuid, ep.source_description AS source_desc",
                params={"uuids": all_episode_uuids},
            )
            for record in result.records:
                ep_uuid = record["uuid"]
                doc_title = _parse_source_description(record["source_desc"])
                if doc_title:
                    episode_sources[ep_uuid] = doc_title
        except Exception:
            logger.debug("episode_source_query_failed", exc_info=True)

    # Build edge-to-source-docs mapping
    edge_sources: dict[int, set[str]] = {}
    for i, edge in enumerate(edges):
        doc_names: set[str] = set()
        for ep_uuid in edge.episodes:
            title = episode_sources.get(ep_uuid)
            if title:
                doc_names.add(title)
        if doc_names:
            edge_sources[i] = doc_names

    # Format results
    parts = []
    for i, edge in enumerate(edges):
        valid_at = edge.valid_at or "unknown"
        invalid_at = edge.invalid_at or "current"
        line = (
            f"- {edge.fact} (relationship: {edge.name}, "
            f"valid: {valid_at}, invalidated: {invalid_at})"
        )
        source_docs = edge_sources.get(i)
        if source_docs:
            line += f" [Source: {', '.join(sorted(source_docs))}]"
        parts.append(line)

    result_text = f"Found {total_count} relationships:\n" + "\n".join(parts)
    result_text = _truncate(result_text, total_count)

    logger.info("graph_search_results", result_count=total_count)
    return result_text


async def get_entity_history(
    graph_service: GraphitiService,
    entity_name: str,
    since: str | None = None,
    reference_time: str | None = None,
) -> str:
    """Get temporal change history for a named entity via direct Cypher.

    Uses case-insensitive regex matching on entity names.  If reference_time is
    provided, returns a point-in-time snapshot (edges valid at that time).

    Returns a formatted text string with source document citations.
    """
    logger.info(
        "graph_entity_history",
        entity_name=entity_name,
        since=since,
        reference_time=reference_time,
    )

    try:
        # Build Cypher query with optional temporal filters
        cypher = (
            "MATCH (n:Entity)-[e:RELATES_TO]-(m:Entity)\n"
            "WHERE n.name =~ $name_pattern\n"
        )
        params: dict[str, str | int | None] = {
            "name_pattern": f"(?i){re.escape(entity_name)}",
        }

        if since:
            cypher += "AND e.created_at >= datetime($since)\n"
            params["since"] = since

        if reference_time:
            cypher += (
                "AND e.valid_at <= datetime($ref_time)\n"
                "AND (e.invalid_at IS NULL OR e.invalid_at > datetime($ref_time))\n"
            )
            params["ref_time"] = reference_time

        cypher += (
            "OPTIONAL MATCH (ep:Episodic)\n"
            "WHERE ep.uuid IN e.episodes\n"
            "WITH e, m, labels(m) AS labels, e.created_at AS created_at,\n"
            "     collect(DISTINCT ep.source_description) AS sources\n"
            "RETURN e.fact AS fact, e.name AS rel_type,\n"
            "       m.name AS related, labels,\n"
            "       e.valid_at AS valid_at, e.invalid_at AS invalid_at,\n"
            "       created_at, sources\n"
            "ORDER BY created_at DESC\n"
            "LIMIT $limit\n"
        )
        params["limit"] = MAX_EDGES

        result = await graph_service.client.driver.execute_query(
            cypher,
            params=params,
        )
        records = result.records
    except Exception:
        logger.warning("graph_history_failed", exc_info=True)
        return "Graph database is currently unavailable."

    if not records:
        return f"No history found for entity '{entity_name}'."

    # Format temporal history
    parts = []
    for record in records:
        invalid_at = record["invalid_at"]
        status = "current" if invalid_at is None else f"superseded {invalid_at}"
        created_at = record["created_at"] or "unknown"
        fact = record["fact"]

        # Extract source documents from episode source_descriptions
        source_descs = record.get("sources") or []
        doc_titles: set[str] = set()
        for desc in source_descs:
            title = _parse_source_description(desc)
            if title:
                doc_titles.add(title)

        # Filter "Entity" from labels
        labels = record.get("labels") or []
        entity_labels = [la for la in labels if la != "Entity"]

        related = record.get("related", "")
        label_str = f" [{', '.join(entity_labels)}]" if entity_labels else ""

        line = f"- [{created_at}] {fact} ({status}) -> {related}{label_str}"
        if doc_titles:
            line += f" [Source: {', '.join(sorted(doc_titles))}]"
        parts.append(line)

    result_text = (
        f"History for '{entity_name}' ({len(records)} changes):\n" + "\n".join(parts)
    )
    if len(result_text) > MAX_CHARS:
        result_text = (
            result_text[: MAX_CHARS - 100]
            + f"\n\n... truncated. {len(records)} total changes."
        )

    logger.info("graph_history_results", result_count=len(records))
    return result_text
