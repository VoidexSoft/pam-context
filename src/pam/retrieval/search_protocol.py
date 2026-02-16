"""SearchService Protocol for type-safe polymorphism between search backends.

Defines the structural interface shared by HybridSearchService and
HaystackSearchService so that deps.py can return a correct type regardless
of which backend is active.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pam.retrieval.types import SearchQuery, SearchResult


@runtime_checkable
class SearchService(Protocol):
    """Structural interface for search service implementations.

    Both HybridSearchService (raw ES) and HaystackSearchService (Haystack pipeline)
    conform to this protocol without explicit inheritance.
    """

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        source_type: str | None = None,
        project: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[SearchResult]: ...

    async def search_from_query(
        self,
        search_query: SearchQuery,
        query_embedding: list[float],
    ) -> list[SearchResult]: ...
