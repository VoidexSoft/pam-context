"""Hybrid search combining vector similarity and BM25 via Elasticsearch RRF."""

import structlog
from elasticsearch import AsyncElasticsearch

from pam.common.config import settings
from pam.retrieval.types import SearchQuery, SearchResult

logger = structlog.get_logger()


class HybridSearchService:
    def __init__(self, client: AsyncElasticsearch, index_name: str | None = None) -> None:
        self.client = client
        self.index_name = index_name or settings.elasticsearch_index

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        source_type: str | None = None,
        project: str | None = None,
    ) -> list[SearchResult]:
        """Perform hybrid search using Elasticsearch RRF (Reciprocal Rank Fusion).

        Combines:
        - BM25 text search on content field
        - kNN vector search on embedding field
        - RRF fusion to merge rankings
        """
        # Build filter clauses
        filters = []
        if source_type:
            filters.append({"term": {"source_type": source_type}})
        if project:
            filters.append({"term": {"project": project}})

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

        response = await self.client.search(index=self.index_name, body=body)

        results = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            results.append(
                SearchResult(
                    segment_id=src.get("segment_id", hit["_id"]),
                    content=src.get("content", ""),
                    score=hit.get("_score", 0.0),
                    source_url=src.get("source_url"),
                    source_id=src.get("source_id"),
                    section_path=src.get("section_path"),
                    document_title=src.get("document_title"),
                    segment_type=src.get("segment_type", "text"),
                )
            )

        logger.info("hybrid_search", query_length=len(query), results=len(results), top_k=top_k)
        return results

    async def search_from_query(self, search_query: SearchQuery, query_embedding: list[float]) -> list[SearchResult]:
        """Convenience method that takes a SearchQuery object."""
        return await self.search(
            query=search_query.query,
            query_embedding=query_embedding,
            top_k=search_query.top_k,
            source_type=search_query.source_type,
            project=search_query.project,
        )
