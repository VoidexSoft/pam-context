"""Tests for the graph pipeline orchestrator."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.graph.pipeline import GraphPipeline


@pytest.fixture
def mock_graph_client():
    client = AsyncMock()
    client.execute_write = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_rel_extractor():
    extractor = AsyncMock()
    extractor.extract_relationships = AsyncMock(return_value=[])
    return extractor


@pytest.fixture
def pipeline(mock_graph_client, mock_rel_extractor):
    return GraphPipeline(
        graph_client=mock_graph_client,
        relationship_extractor=mock_rel_extractor,
    )


def _mock_entity(entity_type: str, data: dict, confidence: float = 0.8, doc_id=None):
    """Create a mock ExtractedEntity ORM object."""
    entity = MagicMock()
    entity.entity_type = entity_type
    entity.entity_data = data
    entity.confidence = confidence
    entity.source_segment_id = uuid.uuid4()
    entity.source_segment = MagicMock()
    entity.source_segment.document_id = doc_id
    return entity


class TestGraphPipeline:
    async def test_process_document_with_entities(self, pipeline, mock_graph_client):
        doc_id = uuid.uuid4()
        entities = [
            _mock_entity("metric_definition", {"name": "DAU", "owner": "Growth"}, doc_id=doc_id),
            _mock_entity("event_tracking_spec", {"event_name": "signup"}, doc_id=doc_id),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = entities
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await pipeline.process_document(doc_id, "Test Doc", mock_session)
        assert count > 0
        # Writer should have been called (upsert_nodes_batch, write_document_edges, etc.)
        assert mock_graph_client.execute_write.call_count > 0

    async def test_process_document_no_entities(self, pipeline, mock_graph_client):
        doc_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await pipeline.process_document(doc_id, "Empty Doc", mock_session)
        assert count == 0

    async def test_filters_entities_to_document(self, pipeline, mock_graph_client):
        doc_id = uuid.uuid4()
        other_doc_id = uuid.uuid4()

        entities = [
            _mock_entity("metric_definition", {"name": "DAU"}, doc_id=doc_id),
            _mock_entity("metric_definition", {"name": "MRR"}, doc_id=other_doc_id),  # Different doc
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = entities
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await pipeline.process_document(doc_id, "Doc 1", mock_session)
        # Only 1 entity (DAU) should be processed, plus its implicit nodes
        assert count >= 1

    async def test_relationship_extraction_failure_doesnt_block(self, pipeline, mock_rel_extractor):
        doc_id = uuid.uuid4()
        entities = [
            _mock_entity("metric_definition", {"name": "DAU"}, doc_id=doc_id),
            _mock_entity("metric_definition", {"name": "MRR"}, doc_id=doc_id),
        ]

        mock_rel_extractor.extract_relationships = AsyncMock(side_effect=Exception("LLM error"))

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = entities
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Should not raise — relationship extraction failure is non-blocking
        count = await pipeline.process_document(doc_id, "Test Doc", mock_session)
        assert count > 0


class TestIngestionPipelineGraphIntegration:
    """Test that IngestionPipeline accepts and uses graph_client."""

    def test_pipeline_accepts_graph_client(self):
        from pam.ingestion.pipeline import IngestionPipeline

        # Just verify the dataclass accepts graph_client
        # Full integration would require all other dependencies
        import dataclasses
        fields = {f.name for f in dataclasses.fields(IngestionPipeline)}
        assert "graph_client" in fields

    def test_pipeline_graph_client_defaults_to_none(self):
        from pam.ingestion.pipeline import IngestionPipeline
        import dataclasses

        field = next(f for f in dataclasses.fields(IngestionPipeline) if f.name == "graph_client")
        assert field.default is None
