"""Writes nodes and relationships to Neo4j with MERGE semantics and temporal edges."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from pam.common.graph import GraphClient
from pam.graph.diff_engine import ChangeType, DiffEngine, EntityChange
from pam.graph.mapper import NodeData
from pam.graph.relationship_extractor import ExtractedRelationship

logger = structlog.get_logger(__name__)


class GraphWriter:
    """Writes graph data to Neo4j using MERGE for idempotent upserts."""

    def __init__(self, client: GraphClient) -> None:
        self._client = client

    async def upsert_node(self, node: NodeData) -> None:
        """MERGE a single node by its unique key."""
        props = {k: v for k, v in node.properties.items() if v is not None}
        key = node.unique_key
        key_value = props.pop(key)

        # Build SET clause for remaining properties
        set_clauses = ", ".join(f"n.{k} = ${k}" for k in props)
        set_part = f"SET {set_clauses}, n.updated_at = datetime()" if set_clauses else "SET n.updated_at = datetime()"

        query = f"MERGE (n:{node.label} {{{key}: ${key}}}) {set_part}"
        params = {key: key_value, **props}
        await self._client.execute_write(query, params)

    async def upsert_nodes_batch(self, nodes: list[NodeData]) -> None:
        """MERGE multiple nodes of the same label using UNWIND for efficiency."""
        if not nodes:
            return

        # Group by label for batched operations
        by_label: dict[str, list[NodeData]] = {}
        for n in nodes:
            by_label.setdefault(n.label, []).append(n)

        for label, label_nodes in by_label.items():
            key = label_nodes[0].unique_key
            # Collect all property keys across all nodes of this label
            all_keys = set()
            for n in label_nodes:
                all_keys.update(k for k, v in n.properties.items() if v is not None and k != key)

            set_clauses = ", ".join(f"n.{k} = item.{k}" for k in sorted(all_keys))
            set_part = f"SET {set_clauses}, n.updated_at = datetime()" if set_clauses else "SET n.updated_at = datetime()"

            query = (
                f"UNWIND $items AS item "
                f"MERGE (n:{label} {{{key}: item.{key}}}) "
                f"{set_part}"
            )

            items = []
            for n in label_nodes:
                item = {k: v for k, v in n.properties.items() if v is not None}
                items.append(item)

            await self._client.execute_write(query, {"items": items})

        logger.info("nodes_upserted", count=len(nodes))

    async def upsert_relationship(
        self,
        from_label: str,
        from_key: str,
        from_value: str,
        rel_type: str,
        to_label: str,
        to_key: str,
        to_value: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """MERGE a relationship between two nodes."""
        props = properties or {}
        now = datetime.now(timezone.utc).isoformat()
        props.setdefault("valid_from", now)
        props.setdefault("created_at", now)

        prop_set = ", ".join(f"r.{k} = ${k}" for k in props)
        set_part = f"SET {prop_set}" if prop_set else ""

        query = (
            f"MATCH (a:{from_label} {{{from_key}: $from_val}}) "
            f"MATCH (b:{to_label} {{{to_key}: $to_val}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"{set_part}"
        )

        params = {"from_val": from_value, "to_val": to_value, **props}
        await self._client.execute_write(query, params)

    async def write_relationships(
        self, relationships: list[ExtractedRelationship]
    ) -> None:
        """Write a list of extracted relationships to the graph."""
        for rel in relationships:
            from_key = "metric" if rel.from_label == "KPI" else "name"
            to_key = "name"

            await self.upsert_relationship(
                from_label=rel.from_label,
                from_key=from_key,
                from_value=rel.from_name,
                rel_type=rel.rel_type,
                to_label=rel.to_label,
                to_key=to_key,
                to_value=rel.to_name,
                properties={"confidence": rel.confidence},
            )

        logger.info("relationships_written", count=len(relationships))

    async def write_document_edges(
        self, document_id: str, document_title: str, nodes: list[NodeData]
    ) -> None:
        """Create DEFINED_IN edges from entity nodes to their source Document node.

        Also creates the Document node if it doesn't exist.
        """
        await self._client.execute_write(
            "MERGE (d:Document {id: $id}) SET d.title = $title, d.updated_at = datetime()",
            {"id": document_id, "title": document_title},
        )

        for node in nodes:
            if node.label in ("Metric", "Event"):
                key = node.unique_key
                name = node.properties[key]
                now = datetime.now(timezone.utc).isoformat()
                await self._client.execute_write(
                    f"MATCH (n:{node.label} {{{key}: $name}}) "
                    f"MATCH (d:Document {{id: $doc_id}}) "
                    f"MERGE (n)-[r:DEFINED_IN]->(d) "
                    f"SET r.valid_from = coalesce(r.valid_from, $now), r.created_at = coalesce(r.created_at, $now)",
                    {"name": name, "doc_id": document_id, "now": now},
                )

    async def write_implicit_edges(self, nodes: list[NodeData]) -> None:
        """Create OWNED_BY and SOURCED_FROM edges from entity properties."""
        now = datetime.now(timezone.utc).isoformat()

        for node in nodes:
            if node.label not in ("Metric", "KPI"):
                continue

            key = node.unique_key
            name = node.properties[key]
            owner = node.properties.get("owner")
            data_source = node.properties.get("data_source")

            if owner:
                await self._client.execute_write(
                    f"MATCH (n:{node.label} {{{key}: $name}}) "
                    f"MATCH (t:Team {{name: $owner}}) "
                    f"MERGE (n)-[r:OWNED_BY]->(t) "
                    f"SET r.valid_from = coalesce(r.valid_from, $now)",
                    {"name": name, "owner": owner, "now": now},
                )

            if data_source and node.label == "Metric":
                await self._client.execute_write(
                    "MATCH (n:Metric {name: $name}) "
                    "MATCH (ds:DataSource {name: $ds}) "
                    "MERGE (n)-[r:SOURCED_FROM]->(ds) "
                    "SET r.valid_from = coalesce(r.valid_from, $now)",
                    {"name": name, "ds": data_source, "now": now},
                )

    async def close_temporal_edge(
        self,
        from_label: str,
        from_key: str,
        from_value: str,
        rel_type: str,
        to_label: str,
        to_key: str,
        to_value: str,
    ) -> None:
        """Set valid_to on an existing temporal edge to mark it as ended."""
        now = datetime.now(timezone.utc).isoformat()
        query = (
            f"MATCH (a:{from_label} {{{from_key}: $from_val}})"
            f"-[r:{rel_type}]->"
            f"(b:{to_label} {{{to_key}: $to_val}}) "
            f"WHERE r.valid_to IS NULL "
            f"SET r.valid_to = $now"
        )
        await self._client.execute_write(query, {"from_val": from_value, "to_val": to_value, "now": now})

    async def apply_changes(self, changes: list[EntityChange]) -> None:
        """Apply entity changes to the graph: version nodes, close/open edges.

        - NEW_ENTITY: node already upserted by pipeline, set version=1
        - DEPRECATED_ENTITY: close all open edges (set valid_to)
        - DEFINITION_CHANGE / OWNERSHIP_CHANGE / TARGET_UPDATE: increment version, log diffs
        """
        now = datetime.now(timezone.utc).isoformat()

        for change in changes:
            label = self._entity_type_to_label(change.entity_type)
            key = self._entity_type_to_key(change.entity_type)

            if change.change_type == ChangeType.NEW_ENTITY:
                await self._client.execute_write(
                    f"MATCH (n:{label} {{{key}: $name}}) "
                    f"SET n.version = coalesce(n.version, 0) + 1, n.created_at = coalesce(n.created_at, $now)",
                    {"name": change.entity_name, "now": now},
                )

            elif change.change_type == ChangeType.DEPRECATED_ENTITY:
                # Close all open edges for this entity
                await self._client.execute_write(
                    f"MATCH (n:{label} {{{key}: $name}})-[r]->() "
                    f"WHERE r.valid_to IS NULL "
                    f"SET r.valid_to = $now",
                    {"name": change.entity_name, "now": now},
                )
                await self._client.execute_write(
                    f"MATCH ()-[r]->(n:{label} {{{key}: $name}}) "
                    f"WHERE r.valid_to IS NULL "
                    f"SET r.valid_to = $now",
                    {"name": change.entity_name, "now": now},
                )

            else:
                # DEFINITION_CHANGE, OWNERSHIP_CHANGE, TARGET_UPDATE
                # Increment version counter
                await self._client.execute_write(
                    f"MATCH (n:{label} {{{key}: $name}}) "
                    f"SET n.version = coalesce(n.version, 0) + 1, n.updated_at = $now",
                    {"name": change.entity_name, "now": now},
                )

        logger.info("changes_applied", count=len(changes))

    @staticmethod
    def _entity_type_to_label(entity_type: str) -> str:
        return {
            "metric_definition": "Metric",
            "event_tracking_spec": "Event",
            "kpi_target": "KPI",
        }.get(entity_type, "Metric")

    @staticmethod
    def _entity_type_to_key(entity_type: str) -> str:
        return {
            "metric_definition": "name",
            "event_tracking_spec": "name",
            "kpi_target": "metric",
        }.get(entity_type, "name")
