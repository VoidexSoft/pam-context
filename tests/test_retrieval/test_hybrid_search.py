"""Tests for HybridSearchService — ES RRF hybrid search."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.types import SearchQuery

SEGMENT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


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


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get_search_results = AsyncMock(return_value=None)
    cache.set_search_results = AsyncMock()
    return cache


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


class TestHybridSearchNullScore:
    """Issue #30.1: _score may be present but None with ES RRF retriever."""

    async def test_null_score_defaults_to_zero(self, mock_es_client):
        hit = _make_es_hit()
        hit["_score"] = None  # RRF retriever can return null _score
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [hit]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert len(results) == 1
        assert results[0].score == 0.0

    async def test_missing_score_defaults_to_zero(self, mock_es_client):
        hit = _make_es_hit()
        del hit["_score"]  # _score key missing entirely
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [hit]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert len(results) == 1
        assert results[0].score == 0.0


class TestHybridSearchSegmentIdFallback:
    """Issue #30.2: segment_id fallback to hit['_id'] can fail UUID parsing."""

    async def test_non_uuid_es_id_generates_deterministic_uuid(self, mock_es_client):
        """When meta.segment_id is missing and _id is not a UUID, a deterministic UUID5 is generated."""
        hit = {
            "_id": "not-a-uuid-string-123",
            "_score": 0.5,
            "_source": {
                "content": "test content",
                "meta": {},  # no segment_id
            },
        }
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [hit]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert len(results) == 1
        # Should be a valid UUID (deterministic from _id)
        expected_uuid = uuid.uuid5(uuid.NAMESPACE_URL, "not-a-uuid-string-123")
        assert results[0].segment_id == expected_uuid

    async def test_valid_uuid_in_meta_used_directly(self, mock_es_client):
        sid = uuid.uuid4()
        hit = _make_es_hit(segment_id=sid)
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [hit]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert results[0].segment_id == sid

    async def test_deterministic_uuid_is_stable(self, mock_es_client):
        """Same _id always produces the same fallback UUID."""
        hit = {
            "_id": "es-doc-abc",
            "_score": 0.5,
            "_source": {"content": "test", "meta": {}},
        }
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [hit, hit]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert results[0].segment_id == results[1].segment_id


class TestHybridSearchEsError:
    """Issue #30.3: No error handling around ES client calls."""

    async def test_es_connection_error_returns_empty(self, mock_es_client):
        mock_es_client.search = AsyncMock(side_effect=ConnectionError("ES unavailable"))
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert results == []

    async def test_es_generic_exception_returns_empty(self, mock_es_client):
        mock_es_client.search = AsyncMock(side_effect=RuntimeError("unexpected"))
        service = HybridSearchService(mock_es_client, index_name="test_idx")

        results = await service.search("test", [0.1] * 1536)

        assert results == []


class TestHybridSearchDateRangeFilter:
    """Issue #31.2: No date range filter tests."""

    async def test_date_from_filter(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        dt_from = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        await service.search("test", [0.1] * 1536, date_from=dt_from)

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        standard = retrievers[0]["standard"]["query"]
        range_filters = [f for f in standard["bool"]["filter"] if "range" in f]
        assert len(range_filters) == 1
        assert "gte" in range_filters[0]["range"]["meta.updated_at"]
        assert range_filters[0]["range"]["meta.updated_at"]["gte"] == dt_from.isoformat()

    async def test_date_to_filter(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        dt_to = datetime(2024, 6, 30, tzinfo=UTC)

        await service.search("test", [0.1] * 1536, date_to=dt_to)

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        standard = retrievers[0]["standard"]["query"]
        range_filters = [f for f in standard["bool"]["filter"] if "range" in f]
        assert len(range_filters) == 1
        assert "lte" in range_filters[0]["range"]["meta.updated_at"]
        assert range_filters[0]["range"]["meta.updated_at"]["lte"] == dt_to.isoformat()

    async def test_date_from_and_date_to_filter(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        dt_from = datetime(2024, 1, 1, tzinfo=UTC)
        dt_to = datetime(2024, 12, 31, tzinfo=UTC)

        await service.search("test", [0.1] * 1536, date_from=dt_from, date_to=dt_to)

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        standard = retrievers[0]["standard"]["query"]
        range_filters = [f for f in standard["bool"]["filter"] if "range" in f]
        assert len(range_filters) == 1
        date_range = range_filters[0]["range"]["meta.updated_at"]
        assert date_range["gte"] == dt_from.isoformat()
        assert date_range["lte"] == dt_to.isoformat()

    async def test_date_filter_also_applied_to_knn(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        dt_from = datetime(2024, 3, 1, tzinfo=UTC)

        await service.search("test", [0.1] * 1536, date_from=dt_from)

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        knn = retrievers[1]["knn"]
        # kNN filter should also include the date range
        assert "filter" in knn
        knn_filter_clauses = knn["filter"]["bool"]["filter"]
        range_filters = [f for f in knn_filter_clauses if "range" in f]
        assert len(range_filters) == 1

    async def test_combined_date_source_project_filters(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        dt_from = datetime(2024, 1, 1, tzinfo=UTC)
        dt_to = datetime(2024, 12, 31, tzinfo=UTC)

        await service.search(
            "test", [0.1] * 1536,
            source_type="markdown", project="finance",
            date_from=dt_from, date_to=dt_to,
        )

        call_body = mock_es_client.search.call_args[1]["body"]
        retrievers = call_body["retriever"]["rrf"]["retrievers"]
        standard = retrievers[0]["standard"]["query"]
        all_filters = standard["bool"]["filter"]
        # Should have: source_type term, project term, and date range
        assert len(all_filters) == 3


class TestHybridSearchCache:
    """Issue #31.1: No cache tests for HybridSearchService."""

    async def test_cache_hit_returns_cached_results(self, mock_es_client, mock_cache: AsyncMock):
        cached_data = [
            {
                "segment_id": str(SEGMENT_ID),
                "content": "cached content",
                "score": 0.9,
                "source_url": None,
                "source_id": None,
                "section_path": None,
                "document_title": None,
                "segment_type": "text",
            }
        ]
        mock_cache.get_search_results.return_value = cached_data

        service = HybridSearchService(mock_es_client, index_name="test_idx", cache=mock_cache)
        results = await service.search("test query", [0.1] * 1536, top_k=5)

        assert len(results) == 1
        assert results[0].segment_id == SEGMENT_ID
        assert results[0].content == "cached content"
        mock_cache.get_search_results.assert_awaited_once_with("test query", 5, None, None, None, None)
        # ES should NOT have been called
        mock_es_client.search.assert_not_called()

    async def test_cache_miss_runs_search_and_caches(self, mock_es_client, mock_cache: AsyncMock):
        mock_cache.get_search_results.return_value = None
        mock_es_client.search = AsyncMock(
            return_value={"hits": {"hits": [_make_es_hit(segment_id=SEGMENT_ID)]}}
        )

        service = HybridSearchService(mock_es_client, index_name="test_idx", cache=mock_cache)
        results = await service.search("test query", [0.1] * 1536, top_k=5)

        assert len(results) == 1
        assert results[0].segment_id == SEGMENT_ID
        mock_es_client.search.assert_called_once()

        # Should have stored in cache
        mock_cache.set_search_results.assert_awaited_once()
        call_args = mock_cache.set_search_results.call_args
        assert call_args[0][0] == "test query"
        assert call_args[0][1] == 5

    async def test_empty_results_not_cached(self, mock_es_client, mock_cache: AsyncMock):
        mock_cache.get_search_results.return_value = None
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": []}})

        service = HybridSearchService(mock_es_client, index_name="test_idx", cache=mock_cache)
        results = await service.search("no results", [0.1] * 1536)

        assert results == []
        # Empty results should NOT be cached (per `if self.cache and results:`)
        mock_cache.set_search_results.assert_not_awaited()

    async def test_cache_receives_json_serializable_data(self, mock_es_client, mock_cache: AsyncMock):
        """Verify model_dump(mode='json') produces str UUIDs, not UUID objects."""
        mock_cache.get_search_results.return_value = None
        mock_es_client.search = AsyncMock(
            return_value={"hits": {"hits": [_make_es_hit(segment_id=SEGMENT_ID)]}}
        )

        service = HybridSearchService(mock_es_client, index_name="test_idx", cache=mock_cache)
        await service.search("test", [0.1] * 1536, top_k=5)

        # The cached data should have string UUIDs, not UUID objects
        call_args = mock_cache.set_search_results.call_args
        cached_results = call_args[0][2]
        assert isinstance(cached_results[0]["segment_id"], str)

    async def test_cache_with_filters(self, mock_es_client, mock_cache: AsyncMock):
        mock_cache.get_search_results.return_value = None
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [_make_es_hit()]}})
        dt_from = datetime(2024, 1, 1, tzinfo=UTC)

        service = HybridSearchService(mock_es_client, index_name="test_idx", cache=mock_cache)
        await service.search("test", [0.1] * 1536, source_type="markdown", project="fin", date_from=dt_from)

        mock_cache.get_search_results.assert_awaited_once_with("test", 10, "markdown", "fin", dt_from, None)
        mock_cache.set_search_results.assert_awaited_once()
        call_args = mock_cache.set_search_results.call_args
        assert call_args[1].get("source_type", call_args[0][3] if len(call_args[0]) > 3 else None) == "markdown"


class TestSearchFromQuery:
    async def test_delegates_to_search(self, mock_es_client):
        mock_es_client.search = AsyncMock(return_value={"hits": {"hits": [_make_es_hit()]}})
        service = HybridSearchService(mock_es_client, index_name="test_idx")
        query = SearchQuery(query="revenue", top_k=5, source_type="markdown")
        results = await service.search_from_query(query, [0.1] * 1536)
        assert len(results) == 1
