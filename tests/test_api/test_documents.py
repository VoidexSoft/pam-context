"""Tests for GET /api/documents endpoint."""

import uuid
from unittest.mock import AsyncMock, Mock


class TestDocumentsEndpoint:
    async def test_list_documents(self, client, mock_api_db_session):
        mock_result = Mock()
        mock_doc = Mock()
        mock_doc.id = uuid.uuid4()
        mock_doc.source_type = "markdown"
        mock_doc.source_id = "/test.md"
        mock_doc.source_url = None
        mock_doc.title = "Test Doc"
        mock_doc.owner = None
        mock_doc.status = "active"
        mock_doc.content_hash = "abc"
        mock_doc.last_synced_at = None
        mock_doc.created_at = None
        mock_result.all.return_value = [(mock_doc, 3)]
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/documents")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Doc"
        assert data[0]["segment_count"] == 3

    async def test_list_empty(self, client, mock_api_db_session):
        mock_result = Mock()
        mock_result.all.return_value = []
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/documents")
        assert response.status_code == 200
        assert response.json() == []
