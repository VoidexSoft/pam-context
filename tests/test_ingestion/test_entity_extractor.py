"""Tests for entity extraction schemas and extractor."""

import json
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from pam.ingestion.extractors.entity_extractor import EntityExtractor
from pam.ingestion.extractors.schemas import (
    EXTRACTION_SCHEMAS,
    EventTrackingSpec,
    ExtractedEntityData,
    KPITarget,
    MetricDefinition,
)


class TestMetricDefinition:
    def test_full_metric(self):
        m = MetricDefinition(
            name="DAU",
            formula="COUNT(DISTINCT user_id) WHERE login_date = today",
            owner="Growth Team",
            data_source="analytics.user_activity_daily",
        )
        assert m.name == "DAU"
        assert m.formula is not None

    def test_minimal_metric(self):
        m = MetricDefinition(name="MRR")
        assert m.name == "MRR"
        assert m.formula is None
        assert m.owner is None


class TestEventTrackingSpec:
    def test_full_event(self):
        e = EventTrackingSpec(
            event_name="signup_completed",
            properties=["user_id", "signup_method", "referral_source"],
            trigger="User submits registration form",
        )
        assert len(e.properties) == 3

    def test_minimal_event(self):
        e = EventTrackingSpec(event_name="page_view")
        assert e.properties == []
        assert e.trigger is None


class TestKPITarget:
    def test_full_target(self):
        k = KPITarget(
            metric="DAU",
            target_value="50000",
            period="Q1 2025",
            owner="Growth Team",
        )
        assert k.target_value == "50000"

    def test_minimal_target(self):
        k = KPITarget(metric="Revenue", target_value="$10M")
        assert k.period is None


class TestExtractedEntityData:
    def test_with_source(self):
        seg_id = uuid.uuid4()
        e = ExtractedEntityData(
            entity_type="metric_definition",
            entity_data={"name": "DAU", "formula": "count(users)"},
            confidence=0.95,
            source_segment_id=seg_id,
            source_text="DAU is the count of users...",
        )
        assert e.entity_type == "metric_definition"
        assert e.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            ExtractedEntityData(
                entity_type="metric_definition",
                entity_data={},
                confidence=1.5,  # Out of range
            )


class TestExtractionSchemas:
    def test_all_schemas_defined(self):
        assert "metric_definition" in EXTRACTION_SCHEMAS
        assert "event_tracking_spec" in EXTRACTION_SCHEMAS
        assert "kpi_target" in EXTRACTION_SCHEMAS

    def test_schemas_have_models(self):
        for info in EXTRACTION_SCHEMAS.values():
            assert "model" in info
            assert "description" in info


class TestEntityExtractor:
    @pytest.fixture
    def mock_anthropic(self):
        return AsyncMock()

    async def test_extract_metric(self, mock_anthropic):
        # Mock Claude response with a metric extraction
        response_data = json.dumps(
            [
                {
                    "entity_type": "metric_definition",
                    "entity_data": {"name": "DAU", "formula": "COUNT(DISTINCT users)"},
                    "confidence": 0.9,
                }
            ]
        )
        text_block = Mock()
        text_block.text = response_data
        response = Mock()
        response.content = [text_block]

        mock_anthropic.messages = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=response)

        extractor = EntityExtractor()
        extractor.client = mock_anthropic

        results = await extractor.extract_from_text("DAU is the count of distinct users per day.")
        assert len(results) == 1
        assert results[0].entity_type == "metric_definition"
        assert results[0].entity_data["name"] == "DAU"
        assert results[0].confidence == 0.9

    async def test_extract_multiple_types(self, mock_anthropic):
        response_data = json.dumps(
            [
                {
                    "entity_type": "metric_definition",
                    "entity_data": {"name": "Conversion Rate", "formula": "signups/visits"},
                    "confidence": 0.85,
                },
                {
                    "entity_type": "kpi_target",
                    "entity_data": {"metric": "Conversion Rate", "target_value": "3.5%", "period": "Q1"},
                    "confidence": 0.8,
                },
            ]
        )
        text_block = Mock()
        text_block.text = response_data
        response = Mock()
        response.content = [text_block]

        mock_anthropic.messages = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=response)

        extractor = EntityExtractor()
        extractor.client = mock_anthropic

        results = await extractor.extract_from_text("Conversion rate is signups/visits. Target: 3.5% for Q1.")
        assert len(results) == 2
        types = {r.entity_type for r in results}
        assert "metric_definition" in types
        assert "kpi_target" in types

    async def test_extract_empty_text(self):
        extractor = EntityExtractor()
        results = await extractor.extract_from_text("")
        assert results == []

    async def test_extract_invalid_json(self, mock_anthropic):
        text_block = Mock()
        text_block.text = "This is not valid JSON"
        response = Mock()
        response.content = [text_block]

        mock_anthropic.messages = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=response)

        extractor = EntityExtractor()
        extractor.client = mock_anthropic

        results = await extractor.extract_from_text("Some text")
        assert results == []

    async def test_extract_unknown_entity_type(self, mock_anthropic):
        response_data = json.dumps([{"entity_type": "unknown_type", "entity_data": {"foo": "bar"}, "confidence": 0.5}])
        text_block = Mock()
        text_block.text = response_data
        response = Mock()
        response.content = [text_block]

        mock_anthropic.messages = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=response)

        extractor = EntityExtractor()
        extractor.client = mock_anthropic

        results = await extractor.extract_from_text("Some text")
        assert results == []  # Unknown types are skipped

    async def test_extract_with_segment_id(self, mock_anthropic):
        seg_id = uuid.uuid4()
        response_data = json.dumps(
            [
                {
                    "entity_type": "kpi_target",
                    "entity_data": {"metric": "DAU", "target_value": "50000"},
                    "confidence": 0.9,
                }
            ]
        )
        text_block = Mock()
        text_block.text = response_data
        response = Mock()
        response.content = [text_block]

        mock_anthropic.messages = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=response)

        extractor = EntityExtractor()
        extractor.client = mock_anthropic

        results = await extractor.extract_from_text("DAU target: 50000", segment_id=seg_id)
        assert len(results) == 1
        assert results[0].source_segment_id == seg_id

    async def test_batch_extraction(self, mock_anthropic):
        response_data = json.dumps(
            [{"entity_type": "metric_definition", "entity_data": {"name": "DAU"}, "confidence": 0.9}]
        )
        text_block = Mock()
        text_block.text = response_data
        response = Mock()
        response.content = [text_block]

        mock_anthropic.messages = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=response)

        extractor = EntityExtractor()
        extractor.client = mock_anthropic

        segments = [
            {"id": uuid.uuid4(), "content": "DAU is daily active users."},
            {"id": uuid.uuid4(), "content": "MRR is monthly recurring revenue."},
        ]

        results = await extractor.extract_from_segments(segments)
        assert len(results) == 2  # One entity per segment
