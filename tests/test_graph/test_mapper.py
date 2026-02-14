"""Tests for entity-to-graph node mapper."""

from __future__ import annotations

import pytest

from pam.graph.mapper import EntityGraphMapper, MappingResult, NodeData


@pytest.fixture
def mapper():
    return EntityGraphMapper()


def _metric(name: str, confidence: float = 0.8, **kwargs) -> dict:
    return {
        "entity_type": "metric_definition",
        "entity_data": {"name": name, **kwargs},
        "confidence": confidence,
        "source_segment_id": None,
    }


def _event(name: str, confidence: float = 0.8, **kwargs) -> dict:
    return {
        "entity_type": "event_tracking_spec",
        "entity_data": {"event_name": name, **kwargs},
        "confidence": confidence,
    }


def _kpi(metric: str, target: str, confidence: float = 0.8, **kwargs) -> dict:
    return {
        "entity_type": "kpi_target",
        "entity_data": {"metric": metric, "target_value": target, **kwargs},
        "confidence": confidence,
    }


class TestMetricMapping:
    def test_maps_basic_metric(self, mapper):
        result = mapper.map_entities([_metric("DAU")])
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.label == "Metric"
        assert node.properties["name"] == "DAU"
        assert node.unique_key == "name"

    def test_maps_metric_with_all_fields(self, mapper):
        result = mapper.map_entities([
            _metric("MRR", formula="sum(revenue)", owner="Finance", data_source="Stripe")
        ])
        node = result.nodes[0]
        assert node.properties["formula"] == "sum(revenue)"
        assert node.properties["owner"] == "Finance"
        assert node.properties["data_source"] == "Stripe"


class TestEventMapping:
    def test_maps_event(self, mapper):
        result = mapper.map_entities([_event("signup_completed", trigger="form submit")])
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.label == "Event"
        assert node.properties["name"] == "signup_completed"
        assert node.properties["trigger"] == "form submit"

    def test_maps_event_properties_list(self, mapper):
        result = mapper.map_entities([_event("page_view", properties=["url", "referrer"])])
        node = result.nodes[0]
        assert node.properties["properties"] == ["url", "referrer"]


class TestKPIMapping:
    def test_maps_kpi(self, mapper):
        result = mapper.map_entities([_kpi("DAU", "50000", period="Q1 2025")])
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.label == "KPI"
        assert node.properties["metric"] == "DAU"
        assert node.properties["target_value"] == "50000"
        assert node.properties["period"] == "Q1 2025"
        assert node.unique_key == "metric"


class TestImplicitNodes:
    def test_extracts_teams_from_owners(self, mapper):
        result = mapper.map_entities([
            _metric("DAU", owner="Growth"),
            _kpi("MRR", "1M", owner="Finance"),
        ])
        team_names = [t.properties["name"] for t in result.implicit_teams]
        assert "Growth" in team_names
        assert "Finance" in team_names

    def test_extracts_data_sources(self, mapper):
        result = mapper.map_entities([
            _metric("DAU", data_source="Mixpanel"),
            _metric("MRR", data_source="Stripe"),
        ])
        ds_names = [ds.properties["name"] for ds in result.implicit_data_sources]
        assert "Mixpanel" in ds_names
        assert "Stripe" in ds_names

    def test_deduplicates_implicit_nodes(self, mapper):
        result = mapper.map_entities([
            _metric("DAU", owner="Growth"),
            _metric("WAU", owner="Growth"),
        ])
        assert len(result.implicit_teams) == 1


class TestDeduplication:
    def test_keeps_highest_confidence(self, mapper):
        result = mapper.map_entities([
            _metric("DAU", confidence=0.6, formula="low-conf"),
            _metric("DAU", confidence=0.9, formula="high-conf"),
        ])
        assert len(result.nodes) == 1
        assert result.nodes[0].properties["formula"] == "high-conf"
        assert result.nodes[0].properties["confidence"] == 0.9

    def test_keeps_first_if_equal_confidence(self, mapper):
        result = mapper.map_entities([
            _metric("DAU", confidence=0.8, formula="first"),
            _metric("DAU", confidence=0.8, formula="second"),
        ])
        assert len(result.nodes) == 1
        assert result.nodes[0].properties["formula"] == "first"


class TestEdgeCases:
    def test_empty_input(self, mapper):
        result = mapper.map_entities([])
        assert len(result.nodes) == 0
        assert len(result.implicit_teams) == 0
        assert len(result.implicit_data_sources) == 0

    def test_unknown_entity_type_skipped(self, mapper):
        result = mapper.map_entities([{
            "entity_type": "unknown_type",
            "entity_data": {"name": "x"},
            "confidence": 0.5,
        }])
        assert len(result.nodes) == 0

    def test_mixed_entity_types(self, mapper):
        result = mapper.map_entities([
            _metric("DAU"),
            _event("signup_completed"),
            _kpi("DAU", "50000"),
        ])
        labels = {n.label for n in result.nodes}
        assert labels == {"Metric", "Event", "KPI"}
        assert len(result.nodes) == 3

    def test_segment_id_stored_as_string(self, mapper):
        import uuid
        sid = uuid.uuid4()
        result = mapper.map_entities([{
            "entity_type": "metric_definition",
            "entity_data": {"name": "X"},
            "confidence": 0.5,
            "source_segment_id": sid,
        }])
        assert result.nodes[0].properties["segment_id"] == str(sid)
