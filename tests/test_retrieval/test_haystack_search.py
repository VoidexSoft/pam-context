"""Tests for HaystackSearchService — Haystack 2.x hybrid search pipeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from haystack import Document

from pam.retrieval.haystack_search import HaystackSearchService
from pam.retrieval.types import SearchQuery, SearchResult

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

SEGMENT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _make_haystack_doc(
    segment_id: uuid.UUID | None = None,
    content: str = "test content",
    score: float = 0.8,
) -> Document:
    sid = str(segment_id or uuid.uuid4())
    return Document(
        id=sid,
        content=content,
        score=score,
        meta={
            "segment_id": sid,
            "source_url": "file:///test.md",
            "source_id": "/test.md",
            "section_path": "Intro",
            "document_title": "Test Doc",
            "segment_type": "text",
        },
    )


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get_search_results = AsyncMock(return_value=None)
    cache.set_search_results = AsyncMock()
    return cache


# ---------------------------------------------------------------------------
# _build_filters
# ---------------------------------------------------------------------------


class TestBuildFilters:
    def test_no_filters_returns_none(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        result = service._build_filters()
        assert result is None

    def test_single_source_type_filter(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        result = service._build_filters(source_type="markdown")

        assert result == {"field": "meta.source_type", "operator": "==", "value": "markdown"}

    def test_single_project_filter(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        result = service._build_filters(project="finance")

        assert result == {"field": "meta.project", "operator": "==", "value": "finance"}

    def test_date_from_filter(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        result = service._build_filters(date_from=dt)

        assert result == {"field": "meta.updated_at", "operator": ">=", "value": dt.isoformat()}

    def test_date_to_filter(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        dt = datetime(2024, 6, 30, tzinfo=UTC)
        result = service._build_filters(date_to=dt)

        assert result == {"field": "meta.updated_at", "operator": "<=", "value": dt.isoformat()}

    def test_multiple_filters_combined_with_and(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        dt_from = datetime(2024, 1, 1, tzinfo=UTC)
        dt_to = datetime(2024, 12, 31, tzinfo=UTC)

        result = service._build_filters(
            source_type="markdown",
            project="finance",
            date_from=dt_from,
            date_to=dt_to,
        )

        assert result["operator"] == "AND"
        conditions = result["conditions"]
        assert len(conditions) == 4
        assert conditions[0] == {"field": "meta.source_type", "operator": "==", "value": "markdown"}
        assert conditions[1] == {"field": "meta.project", "operator": "==", "value": "finance"}
        assert conditions[2] == {"field": "meta.updated_at", "operator": ">=", "value": dt_from.isoformat()}
        assert conditions[3] == {"field": "meta.updated_at", "operator": "<=", "value": dt_to.isoformat()}

    def test_two_filters_combined_with_and(self):
        service = HaystackSearchService(es_url="http://localhost:9200")
        result = service._build_filters(source_type="confluence", project="eng")

        assert result["operator"] == "AND"
        assert len(result["conditions"]) == 2


# ---------------------------------------------------------------------------
# _run_pipeline_sync
# ---------------------------------------------------------------------------


class TestRunPipelineSync:
    def test_without_rerank(self):
        """Pipeline output is read from 'joiner' when reranking is off."""
        docs = [_make_haystack_doc(), _make_haystack_doc()]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": docs}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        results = service._run_pipeline_sync(
            query="test query",
            query_embedding=[0.1] * 10,
            top_k=5,
            filters=None,
        )

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)

        run_data = mock_pipeline.run.call_args[1]["data"]
        assert run_data["bm25_retriever"]["query"] == "test query"
        assert run_data["bm25_retriever"]["top_k"] == 10  # top_k * 2
        assert run_data["embedding_retriever"]["query_embedding"] == [0.1] * 10
        assert run_data["embedding_retriever"]["top_k"] == 10
        assert "ranker" not in run_data

    def test_with_rerank(self):
        """Pipeline output is read from 'ranker' when reranking is on."""
        docs = [_make_haystack_doc(score=0.95)]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"ranker": {"documents": docs}}

        service = HaystackSearchService(es_url="http://localhost:9200", rerank_enabled=True)
        service._pipeline = mock_pipeline

        results = service._run_pipeline_sync(
            query="test query",
            query_embedding=[0.1] * 10,
            top_k=3,
            filters=None,
        )

        assert len(results) == 1
        run_data = mock_pipeline.run.call_args[1]["data"]
        assert "ranker" in run_data
        assert run_data["ranker"]["query"] == "test query"
        assert run_data["ranker"]["top_k"] == 3

    def test_filters_passed_to_both_retrievers(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        filters = {"field": "meta.source_type", "operator": "==", "value": "markdown"}
        service._run_pipeline_sync("q", [0.1], 5, filters)

        run_data = mock_pipeline.run.call_args[1]["data"]
        assert run_data["bm25_retriever"]["filters"] == filters
        assert run_data["embedding_retriever"]["filters"] == filters

    def test_no_filters_omits_filter_key(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        service._run_pipeline_sync("q", [0.1], 5, None)

        run_data = mock_pipeline.run.call_args[1]["data"]
        assert "filters" not in run_data["bm25_retriever"]
        assert "filters" not in run_data["embedding_retriever"]

    def test_trims_results_to_top_k(self):
        docs = [_make_haystack_doc() for _ in range(10)]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": docs}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        results = service._run_pipeline_sync("q", [0.1], 3, None)
        assert len(results) == 3

    def test_empty_pipeline_output(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        results = service._run_pipeline_sync("q", [0.1], 5, None)
        assert results == []

    def test_missing_output_key_returns_empty(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        results = service._run_pipeline_sync("q", [0.1], 5, None)
        assert results == []


# ---------------------------------------------------------------------------
# pipeline property (lazy initialization)
# ---------------------------------------------------------------------------


class TestPipelineProperty:
    @patch("pam.retrieval.haystack_search.ElasticsearchDocumentStore")
    @patch("pam.retrieval.haystack_search.Pipeline")
    @patch("pam.retrieval.haystack_search.ElasticsearchBM25Retriever")
    @patch("pam.retrieval.haystack_search.ElasticsearchEmbeddingRetriever")
    @patch("pam.retrieval.haystack_search.DocumentJoiner")
    def test_lazy_initialization(self, _joiner, _emb_ret, _bm25_ret, mock_pipeline_cls, _ds):
        mock_pipeline_instance = MagicMock()
        mock_pipeline_cls.return_value = mock_pipeline_instance

        service = HaystackSearchService(es_url="http://localhost:9200")
        assert service._pipeline is None

        # First access builds the pipeline
        pipeline = service.pipeline
        assert pipeline is mock_pipeline_instance
        mock_pipeline_instance.add_component.assert_called()

        # Second access returns same instance (no rebuild)
        mock_pipeline_cls.reset_mock()
        pipeline2 = service.pipeline
        assert pipeline2 is pipeline
        mock_pipeline_cls.assert_not_called()

    @patch("pam.retrieval.haystack_search.ElasticsearchDocumentStore")
    @patch("pam.retrieval.haystack_search.Pipeline")
    @patch("pam.retrieval.haystack_search.ElasticsearchBM25Retriever")
    @patch("pam.retrieval.haystack_search.ElasticsearchEmbeddingRetriever")
    @patch("pam.retrieval.haystack_search.DocumentJoiner")
    @patch("pam.retrieval.haystack_search.TransformersSimilarityRanker")
    def test_rerank_enabled_calls_warm_up(self, _ranker, _joiner, _emb_ret, _bm25_ret, mock_pipeline_cls, _ds):
        mock_pipeline_instance = MagicMock()
        mock_pipeline_cls.return_value = mock_pipeline_instance

        service = HaystackSearchService(es_url="http://localhost:9200", rerank_enabled=True)
        _ = service.pipeline

        mock_pipeline_instance.warm_up.assert_called_once()

    @patch("pam.retrieval.haystack_search.ElasticsearchDocumentStore")
    @patch("pam.retrieval.haystack_search.Pipeline")
    @patch("pam.retrieval.haystack_search.ElasticsearchBM25Retriever")
    @patch("pam.retrieval.haystack_search.ElasticsearchEmbeddingRetriever")
    @patch("pam.retrieval.haystack_search.DocumentJoiner")
    def test_no_rerank_does_not_call_warm_up(self, _joiner, _emb_ret, _bm25_ret, mock_pipeline_cls, _ds):
        mock_pipeline_instance = MagicMock()
        mock_pipeline_cls.return_value = mock_pipeline_instance

        service = HaystackSearchService(es_url="http://localhost:9200", rerank_enabled=False)
        _ = service.pipeline

        mock_pipeline_instance.warm_up.assert_not_called()

    @patch("pam.retrieval.haystack_search.ElasticsearchDocumentStore")
    @patch("pam.retrieval.haystack_search.Pipeline")
    @patch("pam.retrieval.haystack_search.ElasticsearchBM25Retriever")
    @patch("pam.retrieval.haystack_search.ElasticsearchEmbeddingRetriever")
    @patch("pam.retrieval.haystack_search.DocumentJoiner")
    @patch("pam.retrieval.haystack_search.TransformersSimilarityRanker")
    def test_rerank_adds_ranker_component(self, mock_ranker_cls, _joiner, _emb_ret, _bm25_ret, mock_pipeline_cls, _ds):
        mock_pipeline_instance = MagicMock()
        mock_pipeline_cls.return_value = mock_pipeline_instance
        mock_ranker = MagicMock()
        mock_ranker_cls.return_value = mock_ranker

        service = HaystackSearchService(es_url="http://localhost:9200", rerank_enabled=True)
        _ = service.pipeline

        # Verify ranker was added
        add_component_calls = mock_pipeline_instance.add_component.call_args_list
        component_names = [call[0][0] for call in add_component_calls]
        assert "ranker" in component_names

        # Verify joiner -> ranker connection
        connect_calls = mock_pipeline_instance.connect.call_args_list
        connect_args = [call[0] for call in connect_calls]
        assert ("joiner.documents", "ranker.documents") in connect_args


# ---------------------------------------------------------------------------
# document_store property (lazy initialization)
# ---------------------------------------------------------------------------


class TestDocumentStoreProperty:
    @patch("pam.retrieval.haystack_search.ElasticsearchDocumentStore")
    def test_lazy_initialization(self, mock_ds_cls):
        mock_ds = MagicMock()
        mock_ds_cls.return_value = mock_ds

        service = HaystackSearchService(es_url="http://es:9200", index_name="my_index")
        assert service._document_store is None

        store = service.document_store
        assert store is mock_ds
        mock_ds_cls.assert_called_once_with(
            hosts="http://es:9200",
            index="my_index",
            embedding_similarity_function="cosine",
        )

        # Second access returns same instance
        mock_ds_cls.reset_mock()
        store2 = service.document_store
        assert store2 is store
        mock_ds_cls.assert_not_called()


# ---------------------------------------------------------------------------
# search() — async
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_cache_hit_returns_cached_results(self, mock_cache: AsyncMock):
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

        service = HaystackSearchService(es_url="http://localhost:9200", cache=mock_cache)
        # Inject a mock pipeline so we can verify it was NOT called
        service._pipeline = MagicMock()

        results = await service.search("test query", [0.1] * 10, top_k=5)

        assert len(results) == 1
        assert results[0].segment_id == SEGMENT_ID
        assert results[0].content == "cached content"
        mock_cache.get_search_results.assert_awaited_once_with("test query", 5, None, None)
        # Pipeline should not have been called
        service._pipeline.run.assert_not_called()

    async def test_cache_miss_runs_pipeline_and_caches(self, mock_cache: AsyncMock):
        mock_cache.get_search_results.return_value = None

        docs = [_make_haystack_doc(segment_id=SEGMENT_ID)]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": docs}}

        service = HaystackSearchService(es_url="http://localhost:9200", cache=mock_cache)
        service._pipeline = mock_pipeline

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            # Make run_in_executor call the function synchronously
            mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, fn, *args: fn(*args))

            results = await service.search("test query", [0.1] * 10, top_k=5)

        assert len(results) == 1
        assert results[0].segment_id == SEGMENT_ID

        # Should have stored in cache
        mock_cache.set_search_results.assert_awaited_once()
        call_args = mock_cache.set_search_results.call_args
        assert call_args[0][0] == "test query"
        assert call_args[0][1] == 5

    async def test_no_cache_configured(self):
        docs = [_make_haystack_doc()]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": docs}}

        service = HaystackSearchService(es_url="http://localhost:9200", cache=None)
        service._pipeline = mock_pipeline

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, fn, *args: fn(*args))

            results = await service.search("test query", [0.1] * 10)

        assert len(results) == 1
        # No errors even without cache

    async def test_empty_results_not_cached(self, mock_cache: AsyncMock):
        mock_cache.get_search_results.return_value = None

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200", cache=mock_cache)
        service._pipeline = mock_pipeline

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, fn, *args: fn(*args))

            results = await service.search("no results", [0.1] * 10)

        assert results == []
        # Empty results should NOT be cached (per the `if self.cache and results:` check)
        mock_cache.set_search_results.assert_not_awaited()

    async def test_search_passes_filters_to_build_filters(self, mock_cache: AsyncMock):
        mock_cache.get_search_results.return_value = None

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200", cache=mock_cache)
        service._pipeline = mock_pipeline

        dt_from = datetime(2024, 1, 1, tzinfo=UTC)
        dt_to = datetime(2024, 12, 31, tzinfo=UTC)

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, fn, *args: fn(*args))

            await service.search(
                "test",
                [0.1] * 10,
                top_k=5,
                source_type="markdown",
                project="finance",
                date_from=dt_from,
                date_to=dt_to,
            )

        # Verify filters were applied to the pipeline run
        run_data = mock_pipeline.run.call_args[1]["data"]
        filters = run_data["bm25_retriever"]["filters"]
        assert filters["operator"] == "AND"
        assert len(filters["conditions"]) == 4

    async def test_runs_pipeline_in_executor(self, mock_cache: AsyncMock):
        """Verify the pipeline is run via run_in_executor to avoid blocking."""
        mock_cache.get_search_results.return_value = None

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200", cache=mock_cache)
        service._pipeline = mock_pipeline

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(return_value=[])

            await service.search("test", [0.1] * 10)

        mock_loop.run_in_executor.assert_awaited_once()
        # First arg should be None (default executor)
        assert mock_loop.run_in_executor.call_args[0][0] is None
        # Second arg is the _run_pipeline_sync method
        assert mock_loop.run_in_executor.call_args[0][1] == service._run_pipeline_sync


# ---------------------------------------------------------------------------
# search_from_query()
# ---------------------------------------------------------------------------


class TestSearchFromQuery:
    async def test_delegates_to_search(self):
        docs = [_make_haystack_doc(segment_id=SEGMENT_ID)]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": docs}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        query = SearchQuery(
            query="revenue",
            top_k=5,
            source_type="markdown",
            project="finance",
        )

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, fn, *args: fn(*args))

            results = await service.search_from_query(query, [0.1] * 10)

        assert len(results) == 1
        assert results[0].segment_id == SEGMENT_ID

        # Verify the pipeline received the correct parameters
        run_data = mock_pipeline.run.call_args[1]["data"]
        assert run_data["bm25_retriever"]["query"] == "revenue"
        assert run_data["bm25_retriever"]["top_k"] == 10  # top_k(5) * 2

    async def test_passes_date_filters(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"joiner": {"documents": []}}

        service = HaystackSearchService(es_url="http://localhost:9200")
        service._pipeline = mock_pipeline

        dt = datetime(2024, 6, 15, tzinfo=UTC)
        query = SearchQuery(query="test", date_from=dt, date_to=dt)

        with patch("asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop
            mock_loop.run_in_executor = AsyncMock(side_effect=lambda _, fn, *args: fn(*args))

            await service.search_from_query(query, [0.1] * 10)

        run_data = mock_pipeline.run.call_args[1]["data"]
        filters = run_data["bm25_retriever"]["filters"]
        assert filters["operator"] == "AND"
        assert len(filters["conditions"]) == 2
