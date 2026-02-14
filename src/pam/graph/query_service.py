"""Graph query interface for knowledge graph traversal and entity history."""

from __future__ import annotations

import re
from typing import Any

import structlog

from pam.common.graph import GraphClient

logger = structlog.get_logger(__name__)

# Cypher keywords that indicate a write operation
_WRITE_KEYWORDS = re.compile(
    r"\b(MERGE|CREATE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s+\{)\b",
    re.IGNORECASE,
)


class GraphQueryService:
    """Read-only query interface over the knowledge graph."""

    def __init__(self, client: GraphClient, max_rows: int = 100) -> None:
        self._client = client
        self._max_rows = max_rows

    async def find_dependencies(self, entity_name: str) -> list[dict[str, Any]]:
        """Find what an entity depends on and what depends on it.

        Traverses DEPENDS_ON edges in both directions.
        Returns: list of {name, direction, confidence, via} dicts.
        """
        query = """
        MATCH (m:Metric {name: $name})-[r:DEPENDS_ON]->(dep:Metric)
        RETURN dep.name AS name, 'depends_on' AS direction,
               r.confidence AS confidence, r.valid_from AS since
        UNION
        MATCH (upstream:Metric)-[r:DEPENDS_ON]->(m:Metric {name: $name})
        RETURN upstream.name AS name, 'depended_by' AS direction,
               r.confidence AS confidence, r.valid_from AS since
        """
        return await self._client.execute_read(query, {"name": entity_name})

    async def find_related(
        self, entity_name: str, max_depth: int = 2
    ) -> list[dict[str, Any]]:
        """Find all entities related to the given entity within max_depth hops.

        Returns subgraph as list of {from_name, from_label, rel_type, to_name, to_label} dicts.
        """
        # Clamp depth to prevent expensive queries
        depth = min(max(max_depth, 1), 4)

        query = f"""
        MATCH path = (start {{name: $name}})-[r*1..{depth}]-(related)
        WHERE start <> related
        UNWIND relationships(path) AS rel
        WITH startNode(rel) AS from_node, rel, endNode(rel) AS to_node
        RETURN DISTINCT
            from_node.name AS from_name,
            labels(from_node)[0] AS from_label,
            type(rel) AS rel_type,
            to_node.name AS to_name,
            labels(to_node)[0] AS to_label,
            rel.confidence AS confidence
        LIMIT $limit
        """
        return await self._client.execute_read(
            query, {"name": entity_name, "limit": self._max_rows}
        )

    async def get_entity_history(
        self, entity_name: str, since: str | None = None
    ) -> list[dict[str, Any]]:
        """Get the change history of an entity from temporal edge properties.

        Returns chronological list of {rel_type, target, valid_from, valid_to, document}.
        """
        params: dict[str, Any] = {"name": entity_name}

        since_clause = ""
        if since:
            since_clause = "AND r.valid_from >= $since"
            params["since"] = since

        query = f"""
        MATCH (n {{name: $name}})-[r]->(target)
        WHERE r.valid_from IS NOT NULL {since_clause}
        OPTIONAL MATCH (n)-[:DEFINED_IN]->(doc:Document)
        RETURN type(r) AS rel_type,
               target.name AS target_name,
               labels(target)[0] AS target_label,
               r.valid_from AS valid_from,
               r.valid_to AS valid_to,
               doc.title AS document_title
        ORDER BY r.valid_from DESC
        LIMIT $limit
        """
        params["limit"] = self._max_rows
        return await self._client.execute_read(query, params)

    async def execute_cypher(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a raw Cypher query with read-only guard.

        Raises ValueError for write operations.
        """
        if _WRITE_KEYWORDS.search(query):
            raise ValueError(
                "Write operations are not allowed. "
                "Only read queries (MATCH, RETURN, WITH, WHERE, ORDER BY, LIMIT) are permitted."
            )

        # Inject LIMIT if not present
        if "LIMIT" not in query.upper():
            query = query.rstrip().rstrip(";") + f" LIMIT {self._max_rows}"

        return await self._client.execute_read(query, params or {})
