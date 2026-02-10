"""Tests for ElasticsearchStore — ES indexing and deletion."""

import uuid
from unittest.mock import AsyncMock

from pam.common.models import KnowledgeSegment
from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore


class TestEnsureIndex:
    async def test_creates_index_when_not_exists(self, mock_es_client):
        mock_es_client.indices.exists = AsyncMock(return_value=False)
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        await store.ensure_index()
        mock_es_client.indices.create.assert_called_once()

    async def test_skips_when_exists(self, mock_es_client):
        mock_es_client.indices.exists = AsyncMock(return_value=True)
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        await store.ensure_index()
        mock_es_client.indices.create.assert_not_called()


class TestBulkIndex:
    async def test_index_segments(self, mock_es_client):
        doc_id = uuid.uuid4()
        segments = [
            KnowledgeSegment(
                content=f"Segment {i}",
                content_hash=f"hash{i}",
                embedding=[0.1] * 1536,
                source_type="markdown",
                source_id="/test.md",
                position=i,
                document_id=doc_id,
            )
            for i in range(3)
        ]
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        count = await store.bulk_index(segments)
        assert count == 3
        mock_es_client.bulk.assert_called_once()

    async def test_empty_segments(self, mock_es_client):
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        count = await store.bulk_index([])
        assert count == 0
        mock_es_client.bulk.assert_not_called()

    async def test_skips_segments_without_embedding(self, mock_es_client):
        segments = [
            KnowledgeSegment(
                content="No embedding",
                content_hash="hash1",
                embedding=None,  # no embedding
                source_type="markdown",
                source_id="/test.md",
                position=0,
            )
        ]
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        count = await store.bulk_index(segments)
        assert count == 0
        mock_es_client.bulk.assert_not_called()

    async def test_handles_bulk_errors(self, mock_es_client):
        mock_es_client.bulk = AsyncMock(
            return_value={
                "errors": True,
                "items": [
                    {"index": {"error": {"type": "mapper_parsing_exception", "reason": "bad"}}}
                ],
            }
        )
        segments = [
            KnowledgeSegment(
                content="test",
                content_hash="h",
                embedding=[0.1] * 1536,
                source_type="markdown",
                source_id="/t.md",
                position=0,
            )
        ]
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        # Should not raise, just log errors
        count = await store.bulk_index(segments)
        assert count == 1


class TestDeleteByDocument:
    async def test_delete(self, mock_es_client):
        mock_es_client.delete_by_query = AsyncMock(return_value={"deleted": 5})
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        deleted = await store.delete_by_document(uuid.uuid4())
        assert deleted == 5
        mock_es_client.delete_by_query.assert_called_once()

    async def test_delete_no_matches(self, mock_es_client):
        mock_es_client.delete_by_query = AsyncMock(return_value={"deleted": 0})
        store = ElasticsearchStore(mock_es_client, index_name="test_index")
        deleted = await store.delete_by_document(uuid.uuid4())
        assert deleted == 0
