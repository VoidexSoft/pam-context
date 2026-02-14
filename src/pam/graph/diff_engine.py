"""Diff engine for detecting changes between entity sets on re-ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ChangeType(str, Enum):
    """Classification of an entity change."""

    NEW_ENTITY = "new_entity"
    DEPRECATED_ENTITY = "deprecated_entity"
    DEFINITION_CHANGE = "definition_change"
    OWNERSHIP_CHANGE = "ownership_change"
    TARGET_UPDATE = "target_update"


@dataclass
class FieldDiff:
    """A single field that changed."""

    field_name: str
    old_value: Any
    new_value: Any


@dataclass
class EntityChange:
    """Represents a detected change to an entity."""

    entity_name: str
    entity_type: str
    change_type: ChangeType
    field_diffs: list[FieldDiff] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Fields that determine ownership vs definition changes
_OWNERSHIP_FIELDS = {"owner"}
_TARGET_FIELDS = {"target_value", "period"}
_IDENTITY_FIELDS = {"name", "event_name", "metric"}  # Used for matching, not diffing


class DiffEngine:
    """Compares old and new entity sets to detect changes."""

    def diff_entities(
        self,
        old_entities: list[dict[str, Any]],
        new_entities: list[dict[str, Any]],
    ) -> list[EntityChange]:
        """Compare two entity sets and return a list of changes.

        Each entity dict should have: entity_type, entity_data, confidence.
        Entities are matched by (entity_type, name_key).
        """
        old_index = self._index_entities(old_entities)
        new_index = self._index_entities(new_entities)

        changes: list[EntityChange] = []

        # Detect added entities
        for key in new_index:
            if key not in old_index:
                entity_type, name = key
                changes.append(EntityChange(
                    entity_name=name,
                    entity_type=entity_type,
                    change_type=ChangeType.NEW_ENTITY,
                ))

        # Detect removed entities
        for key in old_index:
            if key not in new_index:
                entity_type, name = key
                changes.append(EntityChange(
                    entity_name=name,
                    entity_type=entity_type,
                    change_type=ChangeType.DEPRECATED_ENTITY,
                ))

        # Detect modified entities
        for key in old_index:
            if key in new_index:
                old_data = old_index[key]
                new_data = new_index[key]
                entity_type, name = key

                diffs = self._diff_fields(old_data, new_data)
                if diffs:
                    change_type = self._classify_change(entity_type, diffs)
                    changes.append(EntityChange(
                        entity_name=name,
                        entity_type=entity_type,
                        change_type=change_type,
                        field_diffs=diffs,
                    ))

        return changes

    def _index_entities(
        self, entities: list[dict[str, Any]]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Build a lookup index keyed by (entity_type, name)."""
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for entity in entities:
            entity_type = entity["entity_type"]
            data = entity["entity_data"]
            name = self._get_entity_name(entity_type, data)
            if name:
                index[(entity_type, name)] = data
        return index

    @staticmethod
    def _get_entity_name(entity_type: str, data: dict[str, Any]) -> str | None:
        """Extract the identity/name field for an entity type."""
        if entity_type == "metric_definition":
            return data.get("name")
        if entity_type == "event_tracking_spec":
            return data.get("event_name")
        if entity_type == "kpi_target":
            return data.get("metric")
        return None

    @staticmethod
    def _diff_fields(
        old_data: dict[str, Any], new_data: dict[str, Any]
    ) -> list[FieldDiff]:
        """Compare two entity data dicts and return field-level diffs."""
        all_keys = set(old_data.keys()) | set(new_data.keys())
        diffs: list[FieldDiff] = []

        for key in all_keys:
            if key in _IDENTITY_FIELDS:
                continue
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            if old_val != new_val:
                diffs.append(FieldDiff(field_name=key, old_value=old_val, new_value=new_val))

        return diffs

    @staticmethod
    def _classify_change(
        entity_type: str, diffs: list[FieldDiff]
    ) -> ChangeType:
        """Classify the type of change based on which fields changed."""
        changed_fields = {d.field_name for d in diffs}

        if changed_fields <= _OWNERSHIP_FIELDS:
            return ChangeType.OWNERSHIP_CHANGE

        if entity_type == "kpi_target" and changed_fields & _TARGET_FIELDS:
            return ChangeType.TARGET_UPDATE

        return ChangeType.DEFINITION_CHANGE
