"""Abstract base class for rerankers."""

from abc import ABC, abstractmethod

from pam.retrieval.types import SearchResult


class BaseReranker(ABC):
    """Interface for reranking search results given a query."""

    @abstractmethod
    async def rerank(self, query: str, results: list[SearchResult], top_k: int | None = None) -> list[SearchResult]:
        """Rerank search results by relevance to the query.

        Args:
            query: The original search query.
            results: Search results from hybrid search.
            top_k: If set, return only the top K results after reranking.

        Returns:
            Reranked list of SearchResult, highest relevance first.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the reranking model."""
        ...
