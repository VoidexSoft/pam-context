"""Tests for the entity diff engine."""

from __future__ import annotations

import pytest

from pam.graph.diff_engine import ChangeType, DiffEngine, EntityChange, FieldDiff


@pytest.fixture
def engine():
    return DiffEngine()


def _metric(name: str, **kwargs) -> dict:
    return {"entity_type": "metric_definition", "entity_data": {"name": name, **kwargs}, "confidence": 0.8}


def _event(name: str, **kwargs) -> dict:
    return {"entity_type": "event_tracking_spec", "entity_data": {"event_name": name, **kwargs}, "confidence": 0.8}


def _kpi(metric: str, target: str = "100", **kwargs) -> dict:
    return {"entity_type": "kpi_target", "entity_data": {"metric": metric, "target_value": target, **kwargs}, "confidence": 0.8}


class TestNewEntities:
    def test_detects_new_metric(self, engine):
        changes = engine.diff_entities([], [_metric("DAU")])
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.NEW_ENTITY
        assert changes[0].entity_name == "DAU"

    def test_detects_new_event(self, engine):
        changes = engine.diff_entities([], [_event("signup")])
        assert len(changes) == 1
        assert changes[0].entity_type == "event_tracking_spec"

    def test_detects_multiple_new(self, engine):
        changes = engine.diff_entities([], [_metric("DAU"), _metric("MRR")])
        assert len(changes) == 2


class TestDeprecatedEntities:
    def test_detects_removed_metric(self, engine):
        changes = engine.diff_entities([_metric("DAU")], [])
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.DEPRECATED_ENTITY
        assert changes[0].entity_name == "DAU"

    def test_detects_removed_among_others(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU"), _metric("MRR")],
            [_metric("DAU")],
        )
        assert len(changes) == 1
        assert changes[0].entity_name == "MRR"
        assert changes[0].change_type == ChangeType.DEPRECATED_ENTITY


class TestModifiedEntities:
    def test_detects_formula_change(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU", formula="count(users)")],
            [_metric("DAU", formula="count(distinct users)")],
        )
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.DEFINITION_CHANGE
        assert len(changes[0].field_diffs) == 1
        assert changes[0].field_diffs[0].field_name == "formula"
        assert changes[0].field_diffs[0].old_value == "count(users)"
        assert changes[0].field_diffs[0].new_value == "count(distinct users)"

    def test_detects_ownership_change(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU", owner="Growth")],
            [_metric("DAU", owner="Product")],
        )
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.OWNERSHIP_CHANGE

    def test_detects_target_update(self, engine):
        changes = engine.diff_entities(
            [_kpi("DAU", "50000", period="Q1")],
            [_kpi("DAU", "60000", period="Q2")],
        )
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.TARGET_UPDATE

    def test_definition_change_for_mixed_fields(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU", formula="old", owner="Growth")],
            [_metric("DAU", formula="new", owner="Product")],
        )
        assert len(changes) == 1
        # Both formula (definition) and owner (ownership) changed — classified as definition
        assert changes[0].change_type == ChangeType.DEFINITION_CHANGE

    def test_no_change_when_identical(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU", formula="count(users)")],
            [_metric("DAU", formula="count(users)")],
        )
        assert len(changes) == 0


class TestMixedChanges:
    def test_detects_all_change_types(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU"), _metric("MRR", formula="old")],
            [_metric("MRR", formula="new"), _metric("WAU")],
        )
        types = {c.change_type for c in changes}
        names = {c.entity_name for c in changes}
        assert ChangeType.NEW_ENTITY in types  # WAU
        assert ChangeType.DEPRECATED_ENTITY in types  # DAU
        assert ChangeType.DEFINITION_CHANGE in types  # MRR
        assert names == {"DAU", "MRR", "WAU"}

    def test_handles_different_entity_types_same_name(self, engine):
        # A metric and KPI can both reference "DAU" without conflicting
        changes = engine.diff_entities(
            [_metric("DAU")],
            [_metric("DAU"), _kpi("DAU", "50k")],
        )
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.NEW_ENTITY
        assert changes[0].entity_type == "kpi_target"


class TestEdgeCases:
    def test_empty_both(self, engine):
        assert engine.diff_entities([], []) == []

    def test_new_field_added(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU")],
            [_metric("DAU", data_source="Mixpanel")],
        )
        assert len(changes) == 1
        diff = changes[0].field_diffs[0]
        assert diff.field_name == "data_source"
        assert diff.old_value is None
        assert diff.new_value == "Mixpanel"

    def test_field_removed(self, engine):
        changes = engine.diff_entities(
            [_metric("DAU", data_source="Mixpanel")],
            [_metric("DAU")],
        )
        assert len(changes) == 1
        diff = changes[0].field_diffs[0]
        assert diff.old_value == "Mixpanel"
        assert diff.new_value is None

    def test_entity_change_has_timestamp(self, engine):
        changes = engine.diff_entities([], [_metric("DAU")])
        assert changes[0].timestamp is not None
