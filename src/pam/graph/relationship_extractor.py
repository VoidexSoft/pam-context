"""LLM-assisted relationship extraction between entities."""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

from pam.common.config import settings
from pam.graph.mapper import NodeData

logger = structlog.get_logger(__name__)

RELATIONSHIP_PROMPT = """You are a relationship extraction system for a business knowledge graph.

Given a set of entities extracted from the same document, identify relationships between them.

Available relationship types:
- DEPENDS_ON: A metric depends on another metric for its calculation (e.g., "Conversion Rate" depends on "Signups" and "Visits")
- TRACKED_BY: An event is tracked by / feeds into a metric (e.g., "signup_completed" feeds "DAU")
- TARGETS: A KPI targets a specific metric (e.g., KPI "DAU target Q1" targets metric "DAU")

Entities:
{entities}

Output a JSON array of relationships. Each relationship should have:
- "from_name": name of the source entity
- "from_label": label of the source entity (Metric, Event, KPI)
- "rel_type": one of DEPENDS_ON, TRACKED_BY, TARGETS
- "to_name": name of the target entity
- "to_label": label of the target entity (Metric, Event, KPI)
- "confidence": 0.0 to 1.0

Rules:
- DEPENDS_ON: Metric -> Metric only
- TRACKED_BY: Event -> Metric only
- TARGETS: KPI -> Metric only (match KPI.metric to Metric.name)
- Only include relationships with clear evidence from the entity context
- If no relationships are found, output an empty array []

Output (JSON array only, no other text):"""


@dataclass
class ExtractedRelationship:
    """A relationship identified between two entities."""

    from_name: str
    from_label: str
    rel_type: str
    to_name: str
    to_label: str
    confidence: float


VALID_RELATIONSHIPS = {
    "DEPENDS_ON": ("Metric", "Metric"),
    "TRACKED_BY": ("Event", "Metric"),
    "TARGETS": ("KPI", "Metric"),
}


class RelationshipExtractor:
    """Extracts relationships between entities using Claude."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.agent_model

    async def extract_relationships(
        self, nodes: list[NodeData]
    ) -> list[ExtractedRelationship]:
        """Extract relationships between a set of nodes from the same document.

        Also infers direct TARGETS relationships from KPI.metric matching
        Metric.name without needing the LLM.
        """
        if len(nodes) < 2:
            return []

        # Direct inference: KPI -> TARGETS -> Metric (no LLM needed)
        inferred = self._infer_targets(nodes)

        # LLM extraction for complex relationships
        llm_relationships = await self._extract_via_llm(nodes)

        # Combine, dedup by (from_name, rel_type, to_name)
        seen: set[tuple[str, str, str]] = set()
        combined: list[ExtractedRelationship] = []

        for rel in inferred + llm_relationships:
            key = (rel.from_name, rel.rel_type, rel.to_name)
            if key not in seen:
                seen.add(key)
                combined.append(rel)

        return combined

    def _infer_targets(self, nodes: list[NodeData]) -> list[ExtractedRelationship]:
        """Directly infer KPI -> TARGETS -> Metric from matching names."""
        metric_names = {
            n.properties["name"] for n in nodes if n.label == "Metric"
        }
        relationships: list[ExtractedRelationship] = []

        for node in nodes:
            if node.label == "KPI":
                target_metric = node.properties.get("metric", "")
                if target_metric in metric_names:
                    relationships.append(
                        ExtractedRelationship(
                            from_name=target_metric,  # KPI unique key is "metric"
                            from_label="KPI",
                            rel_type="TARGETS",
                            to_name=target_metric,
                            to_label="Metric",
                            confidence=1.0,
                        )
                    )

        return relationships

    async def _extract_via_llm(
        self, nodes: list[NodeData]
    ) -> list[ExtractedRelationship]:
        """Use Claude to identify complex relationships between entities."""
        entities_text = "\n".join(
            f"- [{n.label}] {n.properties.get('name') or n.properties.get('metric', '?')}: "
            f"{json.dumps({k: v for k, v in n.properties.items() if v is not None and k not in ('confidence', 'segment_id')})}"
            for n in nodes
        )

        prompt = RELATIONSHIP_PROMPT.format(entities=entities_text)

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text.strip()  # type: ignore[union-attr]
            raw_relationships = json.loads(raw_text)

            if not isinstance(raw_relationships, list):
                return []

            # Build lookup of known entity names by label
            known: dict[str, set[str]] = {}
            for n in nodes:
                name = n.properties.get("name") or n.properties.get("metric", "")
                known.setdefault(n.label, set()).add(name)

            results: list[ExtractedRelationship] = []
            for raw in raw_relationships:
                rel = self._validate_relationship(raw, known)
                if rel:
                    results.append(rel)

            logger.info("relationships_extracted", count=len(results))
            return results

        except json.JSONDecodeError:
            logger.warning("relationship_extraction_json_parse_failed")
            return []
        except Exception:
            logger.exception("relationship_extraction_failed")
            return []

    def _validate_relationship(
        self, raw: dict, known: dict[str, set[str]]
    ) -> ExtractedRelationship | None:
        """Validate a raw relationship dict against known entities and rules."""
        rel_type = raw.get("rel_type", "")
        if rel_type not in VALID_RELATIONSHIPS:
            return None

        expected_from_label, expected_to_label = VALID_RELATIONSHIPS[rel_type]
        from_label = raw.get("from_label", "")
        to_label = raw.get("to_label", "")

        if from_label != expected_from_label or to_label != expected_to_label:
            return None

        from_name = raw.get("from_name", "")
        to_name = raw.get("to_name", "")

        # Validate endpoints exist
        if from_name not in known.get(from_label, set()):
            return None
        if to_name not in known.get(to_label, set()):
            return None

        confidence = min(max(float(raw.get("confidence", 0.5)), 0.0), 1.0)

        return ExtractedRelationship(
            from_name=from_name,
            from_label=from_label,
            rel_type=rel_type,
            to_name=to_name,
            to_label=to_label,
            confidence=confidence,
        )
