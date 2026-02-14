"""Tests for LLM-assisted relationship extraction."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.graph.mapper import NodeData
from pam.graph.relationship_extractor import (
    ExtractedRelationship,
    RelationshipExtractor,
    VALID_RELATIONSHIPS,
)


@pytest.fixture
def extractor():
    with patch("pam.graph.relationship_extractor.settings") as mock_settings:
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.agent_model = "test-model"
        return RelationshipExtractor(api_key="test-key", model="test-model")


def _metric(name: str, **kwargs) -> NodeData:
    return NodeData(label="Metric", properties={"name": name, **kwargs}, unique_key="name")


def _event(name: str, **kwargs) -> NodeData:
    return NodeData(label="Event", properties={"name": name, **kwargs}, unique_key="name")


def _kpi(metric: str, target: str = "100", **kwargs) -> NodeData:
    return NodeData(
        label="KPI",
        properties={"metric": metric, "target_value": target, **kwargs},
        unique_key="metric",
    )


class TestInferTargets:
    def test_infers_kpi_targets_metric(self, extractor):
        nodes = [_metric("DAU"), _kpi("DAU", "50000")]
        relationships = extractor._infer_targets(nodes)
        assert len(relationships) == 1
        assert relationships[0].rel_type == "TARGETS"
        assert relationships[0].from_label == "KPI"
        assert relationships[0].to_label == "Metric"
        assert relationships[0].confidence == 1.0

    def test_no_match_when_metric_missing(self, extractor):
        nodes = [_metric("MRR"), _kpi("DAU", "50000")]
        relationships = extractor._infer_targets(nodes)
        assert len(relationships) == 0

    def test_multiple_kpis_targeting_different_metrics(self, extractor):
        nodes = [_metric("DAU"), _metric("MRR"), _kpi("DAU", "50k"), _kpi("MRR", "1M")]
        relationships = extractor._infer_targets(nodes)
        assert len(relationships) == 2


class TestValidateRelationship:
    def test_valid_depends_on(self, extractor):
        raw = {
            "from_name": "Conv Rate", "from_label": "Metric",
            "rel_type": "DEPENDS_ON",
            "to_name": "Signups", "to_label": "Metric",
            "confidence": 0.8,
        }
        known = {"Metric": {"Conv Rate", "Signups"}}
        result = extractor._validate_relationship(raw, known)
        assert result is not None
        assert result.rel_type == "DEPENDS_ON"
        assert result.confidence == 0.8

    def test_rejects_invalid_rel_type(self, extractor):
        raw = {
            "from_name": "A", "from_label": "Metric",
            "rel_type": "INVALID",
            "to_name": "B", "to_label": "Metric",
        }
        assert extractor._validate_relationship(raw, {"Metric": {"A", "B"}}) is None

    def test_rejects_wrong_label_pair(self, extractor):
        raw = {
            "from_name": "A", "from_label": "Event",
            "rel_type": "DEPENDS_ON",  # Should be Metric->Metric
            "to_name": "B", "to_label": "Metric",
        }
        assert extractor._validate_relationship(raw, {"Event": {"A"}, "Metric": {"B"}}) is None

    def test_rejects_unknown_endpoint(self, extractor):
        raw = {
            "from_name": "Unknown", "from_label": "Metric",
            "rel_type": "DEPENDS_ON",
            "to_name": "B", "to_label": "Metric",
        }
        assert extractor._validate_relationship(raw, {"Metric": {"B"}}) is None

    def test_clamps_confidence(self, extractor):
        raw = {
            "from_name": "A", "from_label": "Metric",
            "rel_type": "DEPENDS_ON",
            "to_name": "B", "to_label": "Metric",
            "confidence": 1.5,
        }
        result = extractor._validate_relationship(raw, {"Metric": {"A", "B"}})
        assert result is not None
        assert result.confidence == 1.0


class TestExtractViaLLM:
    async def test_parses_llm_response(self, extractor):
        llm_response = json.dumps([{
            "from_name": "Conv Rate", "from_label": "Metric",
            "rel_type": "DEPENDS_ON",
            "to_name": "Signups", "to_label": "Metric",
            "confidence": 0.85,
        }])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=llm_response)]
        extractor.client = AsyncMock()
        extractor.client.messages.create = AsyncMock(return_value=mock_response)

        nodes = [_metric("Conv Rate"), _metric("Signups")]
        results = await extractor._extract_via_llm(nodes)
        assert len(results) == 1
        assert results[0].from_name == "Conv Rate"
        assert results[0].to_name == "Signups"

    async def test_handles_json_parse_error(self, extractor):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not valid json")]
        extractor.client = AsyncMock()
        extractor.client.messages.create = AsyncMock(return_value=mock_response)

        results = await extractor._extract_via_llm([_metric("A"), _metric("B")])
        assert results == []

    async def test_handles_api_error(self, extractor):
        extractor.client = AsyncMock()
        extractor.client.messages.create = AsyncMock(side_effect=Exception("API error"))

        results = await extractor._extract_via_llm([_metric("A"), _metric("B")])
        assert results == []

    async def test_filters_invalid_relationships(self, extractor):
        llm_response = json.dumps([
            {
                "from_name": "A", "from_label": "Metric",
                "rel_type": "DEPENDS_ON",
                "to_name": "B", "to_label": "Metric",
                "confidence": 0.9,
            },
            {
                "from_name": "A", "from_label": "Event",  # Wrong: DEPENDS_ON must be Metric->Metric
                "rel_type": "DEPENDS_ON",
                "to_name": "B", "to_label": "Metric",
                "confidence": 0.8,
            },
        ])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=llm_response)]
        extractor.client = AsyncMock()
        extractor.client.messages.create = AsyncMock(return_value=mock_response)

        results = await extractor._extract_via_llm([_metric("A"), _metric("B")])
        assert len(results) == 1  # Only the valid one


class TestExtractRelationships:
    async def test_returns_empty_for_single_node(self, extractor):
        results = await extractor.extract_relationships([_metric("DAU")])
        assert results == []

    async def test_combines_inferred_and_llm(self, extractor):
        llm_response = json.dumps([{
            "from_name": "signup_completed", "from_label": "Event",
            "rel_type": "TRACKED_BY",
            "to_name": "DAU", "to_label": "Metric",
            "confidence": 0.7,
        }])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=llm_response)]
        extractor.client = AsyncMock()
        extractor.client.messages.create = AsyncMock(return_value=mock_response)

        nodes = [_metric("DAU"), _event("signup_completed"), _kpi("DAU", "50k")]
        results = await extractor.extract_relationships(nodes)

        rel_types = {r.rel_type for r in results}
        assert "TARGETS" in rel_types  # inferred
        assert "TRACKED_BY" in rel_types  # from LLM

    async def test_deduplicates_relationships(self, extractor):
        # LLM returns same TARGETS that was already inferred
        llm_response = json.dumps([{
            "from_name": "DAU", "from_label": "KPI",
            "rel_type": "TARGETS",
            "to_name": "DAU", "to_label": "Metric",
            "confidence": 0.8,
        }])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=llm_response)]
        extractor.client = AsyncMock()
        extractor.client.messages.create = AsyncMock(return_value=mock_response)

        nodes = [_metric("DAU"), _kpi("DAU", "50k")]
        results = await extractor.extract_relationships(nodes)

        targets = [r for r in results if r.rel_type == "TARGETS"]
        assert len(targets) == 1
        assert targets[0].confidence == 1.0  # inferred wins (first)
