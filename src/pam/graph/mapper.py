"""Maps ExtractedEntity records from PostgreSQL into graph node data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeData:
    """Represents a node to be written to the graph."""

    label: str
    properties: dict[str, Any]
    unique_key: str  # Property name used for MERGE (uniqueness)


@dataclass
class MappingResult:
    """All nodes extracted from a set of entities."""

    nodes: list[NodeData] = field(default_factory=list)
    implicit_teams: list[NodeData] = field(default_factory=list)
    implicit_data_sources: list[NodeData] = field(default_factory=list)


class EntityGraphMapper:
    """Maps extracted entities to graph node representations.

    Handles deduplication by entity name, keeping the highest-confidence version.
    Extracts implicit Team and DataSource nodes from entity fields.
    """

    def map_entities(self, entities: list[dict[str, Any]]) -> MappingResult:
        """Map a list of ExtractedEntity-like dicts to graph nodes.

        Each dict should have: entity_type, entity_data, confidence,
        source_segment_id (optional).
        """
        result = MappingResult()
        seen: dict[tuple[str, str], float] = {}  # (label, name) -> best confidence
        teams: set[str] = set()
        data_sources: set[str] = set()

        for entity in entities:
            entity_type = entity["entity_type"]
            data = entity["entity_data"]
            confidence = entity.get("confidence", 0.0)
            segment_id = entity.get("source_segment_id")

            if entity_type == "metric_definition":
                node = self._map_metric(data, confidence, segment_id)
            elif entity_type == "event_tracking_spec":
                node = self._map_event(data, confidence, segment_id)
            elif entity_type == "kpi_target":
                node = self._map_kpi(data, confidence, segment_id)
            else:
                continue

            # Deduplication: keep highest confidence per (label, name)
            name = node.properties[node.unique_key]
            key = (node.label, name)
            if key in seen and seen[key] >= confidence:
                continue
            seen[key] = confidence

            # Remove existing node with same label+name if we're replacing it
            result.nodes = [
                n for n in result.nodes
                if not (n.label == node.label and n.properties.get(n.unique_key) == name)
            ]
            result.nodes.append(node)

            # Extract implicit nodes
            owner = data.get("owner")
            if owner:
                teams.add(owner)
            data_source = data.get("data_source")
            if data_source:
                data_sources.add(data_source)

        result.implicit_teams = [
            NodeData(label="Team", properties={"name": t}, unique_key="name")
            for t in sorted(teams)
        ]
        result.implicit_data_sources = [
            NodeData(label="DataSource", properties={"name": ds}, unique_key="name")
            for ds in sorted(data_sources)
        ]

        return result

    def _map_metric(
        self, data: dict[str, Any], confidence: float, segment_id: Any
    ) -> NodeData:
        return NodeData(
            label="Metric",
            properties={
                "name": data["name"],
                "formula": data.get("formula"),
                "owner": data.get("owner"),
                "data_source": data.get("data_source"),
                "confidence": confidence,
                "segment_id": str(segment_id) if segment_id else None,
            },
            unique_key="name",
        )

    def _map_event(
        self, data: dict[str, Any], confidence: float, segment_id: Any
    ) -> NodeData:
        return NodeData(
            label="Event",
            properties={
                "name": data["event_name"],
                "properties": data.get("properties", []),
                "trigger": data.get("trigger"),
                "confidence": confidence,
                "segment_id": str(segment_id) if segment_id else None,
            },
            unique_key="name",
        )

    def _map_kpi(
        self, data: dict[str, Any], confidence: float, segment_id: Any
    ) -> NodeData:
        return NodeData(
            label="KPI",
            properties={
                "metric": data["metric"],
                "target_value": data["target_value"],
                "period": data.get("period"),
                "owner": data.get("owner"),
                "confidence": confidence,
                "segment_id": str(segment_id) if segment_id else None,
            },
            unique_key="metric",
        )
