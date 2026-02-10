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
