"""Tests for POST /api/search endpoint."""

import uuid
from unittest.mock import AsyncMock

from pam.retrieval.types import SearchResult


class TestSearchEndpoint:
    async def test_search_success(self, client, mock_search_service, mock_api_embedder):
        sid = uuid.uuid4()
        mock_search_service.search_from_query = AsyncMock(
            return_value=[
                SearchResult(
                    segment_id=sid,
                    content="Revenue was $10M",
                    score=0.95,
                    document_title="Report",
                )
            ]
        )
        response = await client.post(
            "/api/search",
            json={"query": "revenue"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "Revenue was $10M"

    async def test_search_validation_error(self, client):
        response = await client.post("/api/search", json={})
        assert response.status_code == 422

    async def test_search_empty_results(self, client, mock_search_service):
        mock_search_service.search_from_query = AsyncMock(return_value=[])
        response = await client.post(
            "/api/search",
            json={"query": "nonexistent"},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_search_with_filters(self, client, mock_search_service, mock_api_embedder):
        """Filter parameters are forwarded to the search service via SearchQuery."""
        mock_search_service.search_from_query = AsyncMock(return_value=[])

        response = await client.post(
            "/api/search",
            json={
                "query": "revenue",
                "source_type": "confluence",
                "project": "alpha",
                "date_from": "2024-01-01T00:00:00",
                "date_to": "2024-12-31T23:59:59",
            },
        )
        assert response.status_code == 200

        # The search service should have been called with the SearchQuery object
        call_args = mock_search_service.search_from_query.call_args
        query_arg = call_args[0][0]
        assert query_arg.source_type == "confluence"
        assert query_arg.project == "alpha"
        assert query_arg.date_from is not None
        assert query_arg.date_to is not None

    async def test_search_top_k_parameter(self, client, mock_search_service, mock_api_embedder):
        """Custom top_k value is propagated through the SearchQuery."""
        mock_search_service.search_from_query = AsyncMock(return_value=[])

        response = await client.post(
            "/api/search",
            json={"query": "revenue", "top_k": 25},
        )
        assert response.status_code == 200

        call_args = mock_search_service.search_from_query.call_args
        query_arg = call_args[0][0]
        assert query_arg.top_k == 25

    async def test_search_top_k_validation(self, client):
        """top_k outside the allowed range [1, 50] returns 422."""
        # top_k = 0 should fail (ge=1)
        response = await client.post(
            "/api/search",
            json={"query": "revenue", "top_k": 0},
        )
        assert response.status_code == 422

        # top_k = 51 should fail (le=50)
        response = await client.post(
            "/api/search",
            json={"query": "revenue", "top_k": 51},
        )
        assert response.status_code == 422
