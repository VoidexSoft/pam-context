"""Haystack 2.x-based hybrid search service (drop-in replacement for HybridSearchService)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog
from haystack import Pipeline
from haystack.components.joiners.document_joiner import DocumentJoiner
from haystack.components.rankers import TransformersSimilarityRanker
from haystack_integrations.components.retrievers.elasticsearch import (
    ElasticsearchBM25Retriever,
    ElasticsearchEmbeddingRetriever,
)
from haystack_integrations.document_stores.elasticsearch import ElasticsearchDocumentStore

from pam.common.cache import CacheService
from pam.common.config import settings
from pam.common.haystack_adapter import haystack_doc_to_search_result
from pam.retrieval.types import SearchQuery, SearchResult

logger = structlog.get_logger()


class HaystackSearchService:
    """Hybrid search using Haystack's component pipeline with ES BM25 + kNN + RRF fusion."""

    def __init__(
        self,
        es_url: str | None = None,
        index_name: str | None = None,
        cache: CacheService | None = None,
        rerank_enabled: bool = False,
        rerank_model: str | None = None,
    ) -> None:
        self._es_url = es_url or settings.elasticsearch_url
        self._index_name = index_name or settings.elasticsearch_index
        self.cache = cache
        self._rerank_enabled = rerank_enabled
        self._rerank_model = rerank_model or settings.rerank_model
        self._pipeline: Pipeline | None = None
        self._document_store: ElasticsearchDocumentStore | None = None

    @property
    def document_store(self) -> ElasticsearchDocumentStore:
        if self._document_store is None:
            self._document_store = ElasticsearchDocumentStore(
                hosts=self._es_url,
                index=self._index_name,
                embedding_similarity_function="cosine",
            )
        return self._document_store

    def _build_pipeline(self) -> Pipeline:
        """Build a Haystack hybrid retrieval pipeline."""
        pipeline = Pipeline()

        bm25_retriever = ElasticsearchBM25Retriever(
            document_store=self.document_store,
        )
        embedding_retriever = ElasticsearchEmbeddingRetriever(
            document_store=self.document_store,
        )
        joiner = DocumentJoiner(
            join_mode="reciprocal_rank_fusion",
        )

        pipeline.add_component("bm25_retriever", bm25_retriever)
        pipeline.add_component("embedding_retriever", embedding_retriever)
        pipeline.add_component("joiner", joiner)

        pipeline.connect("bm25_retriever.documents", "joiner.documents")
        pipeline.connect("embedding_retriever.documents", "joiner.documents")

        if self._rerank_enabled:
            ranker = TransformersSimilarityRanker(
                model=self._rerank_model,
            )
            pipeline.add_component("ranker", ranker)
            pipeline.connect("joiner.documents", "ranker.documents")

        return pipeline

    @property
    def pipeline(self) -> Pipeline:
        if self._pipeline is None:
            self._pipeline = self._build_pipeline()
            if self._rerank_enabled:
                self._pipeline.warm_up()
        return self._pipeline

    def _build_filters(
        self,
        source_type: str | None = None,
        project: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict | None:
        """Build Haystack-style metadata filters."""
        conditions = []

        if source_type:
            conditions.append({"field": "meta.source_type", "operator": "==", "value": source_type})
        if project:
            conditions.append({"field": "meta.project", "operator": "==", "value": project})
        if date_from:
            conditions.append({"field": "meta.updated_at", "operator": ">=", "value": date_from.isoformat()})
        if date_to:
            conditions.append({"field": "meta.updated_at", "operator": "<=", "value": date_to.isoformat()})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"operator": "AND", "conditions": conditions}

    def _run_pipeline_sync(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None,
    ) -> list[SearchResult]:
        """Run the Haystack pipeline synchronously (called via run_in_executor)."""
        run_data: dict = {
            "bm25_retriever": {"query": query, "top_k": top_k * 2},
            "embedding_retriever": {"query_embedding": query_embedding, "top_k": top_k * 2},
        }

        if filters:
            run_data["bm25_retriever"]["filters"] = filters
            run_data["embedding_retriever"]["filters"] = filters

        if self._rerank_enabled:
            run_data["ranker"] = {"query": query, "top_k": top_k}

        result = self.pipeline.run(data=run_data)

        # Get documents from the last component
        output_key = "ranker" if self._rerank_enabled else "joiner"
        docs = result.get(output_key, {}).get("documents", [])

        # Trim to top_k (joiner may return more)
        docs = docs[:top_k]

        return [haystack_doc_to_search_result(doc) for doc in docs]

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        source_type: str | None = None,
        project: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[SearchResult]:
        """Perform hybrid search using Haystack pipeline (async wrapper)."""
        # Check cache first
        if self.cache:
            cached = await self.cache.get_search_results(query, top_k, source_type, project, date_from, date_to)
            if cached is not None:
                logger.info("haystack_search_cache_hit", query_length=len(query))
                return [SearchResult(**r) for r in cached]

        filters = self._build_filters(source_type, project, date_from, date_to)

        # Haystack pipelines are sync — run in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            self._run_pipeline_sync,
            query,
            query_embedding,
            top_k,
            filters,
        )

        logger.info("haystack_search", query_length=len(query), results=len(results), top_k=top_k)

        # Store in cache
        if self.cache and results:
            await self.cache.set_search_results(
                query, top_k, [r.model_dump() for r in results],
                source_type, project, date_from, date_to,
            )

        return results

    async def search_from_query(self, search_query: SearchQuery, query_embedding: list[float]) -> list[SearchResult]:
        """Convenience method that takes a SearchQuery object."""
        return await self.search(
            query=search_query.query,
            query_embedding=query_embedding,
            top_k=search_query.top_k,
            source_type=search_query.source_type,
            project=search_query.project,
            date_from=search_query.date_from,
            date_to=search_query.date_to,
        )
