"""Tests for graph edge versioning on re-ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pam.graph.diff_engine import ChangeType, EntityChange, FieldDiff
from pam.graph.writer import GraphWriter


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.execute_write = AsyncMock(return_value=[])
    return client


@pytest.fixture
def writer(mock_client):
    return GraphWriter(mock_client)


class TestApplyNewEntity:
    async def test_sets_version_on_new_entity(self, writer, mock_client):
        changes = [EntityChange(
            entity_name="DAU",
            entity_type="metric_definition",
            change_type=ChangeType.NEW_ENTITY,
        )]
        await writer.apply_changes(changes)
        query = mock_client.execute_write.call_args[0][0]
        assert "version" in query
        assert "Metric" in query


class TestApplyDeprecatedEntity:
    async def test_closes_outgoing_edges(self, writer, mock_client):
        changes = [EntityChange(
            entity_name="OldMetric",
            entity_type="metric_definition",
            change_type=ChangeType.DEPRECATED_ENTITY,
        )]
        await writer.apply_changes(changes)
        # Should close both outgoing and incoming edges
        assert mock_client.execute_write.call_count == 2
        queries = [c[0][0] for c in mock_client.execute_write.call_args_list]
        assert any("valid_to" in q and "(n:Metric" in q and "-[r]->(" in q for q in queries)
        assert any("valid_to" in q and "->(n:Metric" in q for q in queries)

    async def test_only_closes_open_edges(self, writer, mock_client):
        changes = [EntityChange(
            entity_name="Old",
            entity_type="metric_definition",
            change_type=ChangeType.DEPRECATED_ENTITY,
        )]
        await writer.apply_changes(changes)
        for call in mock_client.execute_write.call_args_list:
            query = call[0][0]
            assert "valid_to IS NULL" in query


class TestApplyModifiedEntity:
    async def test_increments_version_on_definition_change(self, writer, mock_client):
        changes = [EntityChange(
            entity_name="DAU",
            entity_type="metric_definition",
            change_type=ChangeType.DEFINITION_CHANGE,
            field_diffs=[FieldDiff("formula", "old", "new")],
        )]
        await writer.apply_changes(changes)
        query = mock_client.execute_write.call_args[0][0]
        assert "version" in query
        assert "coalesce" in query

    async def test_increments_version_on_ownership_change(self, writer, mock_client):
        changes = [EntityChange(
            entity_name="DAU",
            entity_type="metric_definition",
            change_type=ChangeType.OWNERSHIP_CHANGE,
            field_diffs=[FieldDiff("owner", "Growth", "Product")],
        )]
        await writer.apply_changes(changes)
        assert mock_client.execute_write.call_count == 1

    async def test_increments_version_on_target_update(self, writer, mock_client):
        changes = [EntityChange(
            entity_name="DAU",
            entity_type="kpi_target",
            change_type=ChangeType.TARGET_UPDATE,
            field_diffs=[FieldDiff("target_value", "50000", "60000")],
        )]
        await writer.apply_changes(changes)
        query = mock_client.execute_write.call_args[0][0]
        assert "KPI" in query
        assert "metric" in query  # KPI uses "metric" as key


class TestApplyMultipleChanges:
    async def test_applies_all_changes(self, writer, mock_client):
        changes = [
            EntityChange("NewMetric", "metric_definition", ChangeType.NEW_ENTITY),
            EntityChange("OldMetric", "metric_definition", ChangeType.DEPRECATED_ENTITY),
            EntityChange("DAU", "metric_definition", ChangeType.DEFINITION_CHANGE,
                         field_diffs=[FieldDiff("formula", "a", "b")]),
        ]
        await writer.apply_changes(changes)
        # NEW: 1 call, DEPRECATED: 2 calls, MODIFIED: 1 call = 4 total
        assert mock_client.execute_write.call_count == 4


class TestEntityTypeMapping:
    def test_metric_label(self):
        assert GraphWriter._entity_type_to_label("metric_definition") == "Metric"

    def test_event_label(self):
        assert GraphWriter._entity_type_to_label("event_tracking_spec") == "Event"

    def test_kpi_label(self):
        assert GraphWriter._entity_type_to_label("kpi_target") == "KPI"

    def test_kpi_key(self):
        assert GraphWriter._entity_type_to_key("kpi_target") == "metric"

    def test_metric_key(self):
        assert GraphWriter._entity_type_to_key("metric_definition") == "name"
