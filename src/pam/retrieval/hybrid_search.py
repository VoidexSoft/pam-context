"""Hybrid search combining vector similarity and BM25 via Elasticsearch RRF.

Note: This is the legacy search service using raw ES queries. When
settings.use_haystack_retrieval is True, HaystackSearchService is used instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from elasticsearch import AsyncElasticsearch

from pam.common.cache import CacheService
from pam.retrieval.rerankers.base import BaseReranker
from pam.retrieval.types import SearchQuery, SearchResult

logger = structlog.get_logger()


class HybridSearchService:
    def __init__(
        self,
        client: AsyncElasticsearch,
        index_name: str,
        cache: CacheService | None = None,
        reranker: BaseReranker | None = None,
    ) -> None:
        self.client = client
        self.index_name = index_name
        self.cache = cache
        self.reranker = reranker

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
        """Perform hybrid search using Elasticsearch RRF (Reciprocal Rank Fusion).

        Combines:
        - BM25 text search on content field
        - kNN vector search on embedding field
        - RRF fusion to merge rankings
        """
        # Check cache first
        if self.cache:
            cached = await self.cache.get_search_results(query, top_k, source_type, project, date_from, date_to)
            if cached is not None:
                logger.info("hybrid_search_cache_hit", query_length=len(query))
                return [SearchResult(**r) for r in cached]

        # Build filter clauses (metadata fields are nested under meta.*)
        filters: list[dict] = []
        if source_type:
            filters.append({"term": {"meta.source_type": source_type}})
        if project:
            filters.append({"term": {"meta.project": project}})
        if date_from or date_to:
            date_range: dict[str, str] = {}
            if date_from:
                date_range["gte"] = date_from.isoformat()
            if date_to:
                date_range["lte"] = date_to.isoformat()
            filters.append({"range": {"meta.updated_at": date_range}})

        # Build RRF retriever query (ES 8.x)
        standard_query: dict = {"match": {"content": query}}
        if filters:
            standard_query = {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": filters,
                }
            }

        knn_filter = filters if filters else None

        body: dict = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {"standard": {"query": standard_query}},
                        {
                            "knn": {
                                "field": "embedding",
                                "query_vector": query_embedding,
                                "k": top_k,
                                "num_candidates": top_k * 10,
                                **({"filter": {"bool": {"filter": knn_filter}}} if knn_filter else {}),
                            }
                        },
                    ],
                    "rank_window_size": top_k * 2,
                    "rank_constant": 60,
                }
            },
            "size": top_k,
            "_source": {
                "excludes": ["embedding"],
            },
        }

        try:
            response = await self.client.search(index=self.index_name, body=body)
        except Exception:
            logger.exception(
                "hybrid_search_es_error",
                query_length=len(query),
                top_k=top_k,
                source_type=source_type,
                project=project,
            )
            return []

        results = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            meta = src.get("meta", {})

            # _score may be present but None when using RRF retriever
            score = hit.get("_score") or 0.0

            # segment_id fallback: ES _id may not be a valid UUID, so
            # generate a deterministic UUID5 from the string if parsing fails
            raw_segment_id = meta.get("segment_id") or hit["_id"]
            try:
                segment_id = uuid.UUID(str(raw_segment_id))
            except (ValueError, AttributeError):
                segment_id = uuid.uuid5(uuid.NAMESPACE_URL, str(hit["_id"]))

            results.append(
                SearchResult(
                    segment_id=segment_id,
                    content=src.get("content", ""),
                    score=score,
                    source_url=meta.get("source_url"),
                    source_id=meta.get("source_id"),
                    section_path=meta.get("section_path"),
                    document_title=meta.get("document_title"),
                    segment_type=meta.get("segment_type", "text"),
                )
            )

        logger.info("hybrid_search", query_length=len(query), results=len(results), top_k=top_k)

        # Rerank results if reranker is configured
        if self.reranker and results:
            results = await self.reranker.rerank(query, results, top_k=top_k)

        # Store in cache (after reranking so cached results are already reranked)
        if self.cache and results:
            await self.cache.set_search_results(
                query,
                top_k,
                [r.model_dump(mode="json") for r in results],
                source_type,
                project,
                date_from,
                date_to,
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
