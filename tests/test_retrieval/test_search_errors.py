"""Tests for search error propagation."""

import pytest
from unittest.mock import AsyncMock

from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.types import SearchBackendError


@pytest.mark.asyncio
async def test_hybrid_search_raises_on_es_error():
    """HybridSearchService raises SearchBackendError on ES failure."""
    mock_client = AsyncMock()
    mock_client.search = AsyncMock(side_effect=ConnectionError("ES down"))

    service = HybridSearchService(mock_client, index_name="test")
    with pytest.raises(SearchBackendError, match="ES down"):
        await service.search(query="test", query_embedding=[0.1] * 1536)


@pytest.mark.asyncio
async def test_hybrid_search_returns_results_normally():
    """HybridSearchService returns results when ES is healthy."""
    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value={"hits": {"hits": []}})

    service = HybridSearchService(mock_client, index_name="test")
    results = await service.search(query="test", query_embedding=[0.1] * 1536)
    assert results == []
