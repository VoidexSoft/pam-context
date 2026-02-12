"""Tests for HybridSearchService — ES RRF hybrid search."""

import uuid
from unittest.mock import AsyncMock

from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.types import SearchQuery


def _make_es_hit(segment_id=None, content="test content", score=1.0):
    sid = str(segment_id or uuid.uuid4())
    return {
        "_id": sid,
        "_score": score,
        "_source": {
            "content": content,
            "meta": {
                "segment_id": sid,
                "source_url": "file:///test.md",
                "source_id": "/test.md",
                "section_path": "Intro",
                "document_title": "Test Doc",
                "segment_type": "text",
            },
        },
    }


class TestHybridSearch:
    async def test_search_with_results(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [_make_es_hit(), _make_es_hit()]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        results = await service.search(
            query="revenue",
            query_embedding=[0.1] * 1536,
            top_k=10,
        )
        assert len(results) == 2
        assert results[0].content == "test content"
        assert results[0].document_title == "Test Doc"
        mock_es_client.search.assert_called_once()

    async def test_search_empty_results(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        results = await service.search("nothing", [0.1] * 1536)
        assert results == []

    async def test_search_with_source_type_filter(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        await service.search("test", [0.1] * 1536, source_type="markdown")

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        # The standard retriever should include a filter
        standard = retrievers[0]["standard"]["query"]
        assert "bool" in standard
        assert any(f.get("term", {}).get("meta.source_type") == "markdown" for f in standard["bool"]["filter"])

    async def test_search_with_project_filter(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        await service.search("test", [0.1] * 1536, project="finance")

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        standard = retrievers[0]["standard"]["query"]
        assert any(f.get("term", {}).get("meta.project") == "finance" for f in standard["bool"]["filter"])

    async def test_search_respects_top_k(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        await service.search("test", [0.1] * 1536, top_k=5)

        call_body = mock_es_client.search.call_args[1]["body"]
        assert call_body["size"] == 5


class TestSearchFromQuery:
    async def test_delegates_to_search(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [_make_es_hit()]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        query = SearchQuery(query="revenue", top_k=5, source_type="markdown")
        results = await service.search_from_query(query, [0.1] * 1536)
        assert len(results) == 1
