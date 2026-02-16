"""Tests for cursor-based pagination utilities and endpoint pagination behavior."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from pam.api.pagination import DEFAULT_PAGE_SIZE, PaginatedResponse, decode_cursor, encode_cursor


class TestCursorEncoding:
    def test_encode_decode_roundtrip(self):
        """Encoding and decoding a cursor should return the original values."""
        item_id = str(uuid.uuid4())
        sort_value = datetime.now(UTC).isoformat()

        cursor = encode_cursor(item_id, sort_value)
        decoded = decode_cursor(cursor)

        assert decoded["id"] == item_id
        assert decoded["sv"] == sort_value

    def test_encode_produces_base64_string(self):
        """Encoded cursor should be a non-empty base64 URL-safe string."""
        cursor = encode_cursor("abc", "2024-01-01T00:00:00")
        assert isinstance(cursor, str)
        assert len(cursor) > 0
        # URL-safe base64 characters only
        import re

        assert re.match(r"^[A-Za-z0-9_=-]+$", cursor)

    def test_decode_invalid_cursor_raises(self):
        """Decoding an invalid cursor should raise an error."""
        with pytest.raises(Exception):
            decode_cursor("not-valid-base64!!!")


class TestPaginatedResponse:
    def test_default_cursor_is_empty(self):
        response = PaginatedResponse(items=[], total=0)
        assert response.cursor == ""

    def test_with_items(self):
        response = PaginatedResponse(items=["a", "b"], total=2, cursor="abc")
        assert len(response.items) == 2
        assert response.total == 2
        assert response.cursor == "abc"

    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 50


class TestDocumentPagination:
    """Test pagination behavior on the /documents endpoint."""

    async def test_returns_paginated_envelope(self, client, mock_api_db_session):
        """GET /documents should return {items, total, cursor} envelope."""
        now = datetime.now(UTC)
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
        mock_doc.created_at = now
        mock_doc.updated_at = now

        count_result = Mock()
        count_result.scalar.return_value = 1

        doc_result = Mock()
        doc_result.all.return_value = [(mock_doc, 3)]

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, doc_result])

        response = await client.get("/api/documents?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "cursor" in data
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_empty_cursor_on_last_page(self, client, mock_api_db_session):
        """When there are no more pages, cursor should be empty string."""
        count_result = Mock()
        count_result.scalar.return_value = 0

        doc_result = Mock()
        doc_result.all.return_value = []

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, doc_result])

        response = await client.get("/api/documents")
        data = response.json()
        assert data["cursor"] == ""

    async def test_invalid_cursor_returns_400(self, client, mock_api_db_session):
        """Invalid cursor parameter should return 400."""
        count_result = Mock()
        count_result.scalar.return_value = 0
        mock_api_db_session.execute = AsyncMock(return_value=count_result)

        response = await client.get("/api/documents?cursor=invalid!!!")
        assert response.status_code == 400
        assert "cursor" in response.json()["detail"].lower()

    async def test_cursor_pagination_traversal(self, client, mock_api_db_session):
        """Two pages of results should not overlap when following cursor."""
        now = datetime.now(UTC)

        # Page 1: 2 docs + 1 extra (has_next=True)
        doc1 = Mock()
        doc1.id = uuid.uuid4()
        doc1.source_type = "markdown"
        doc1.source_id = "/a.md"
        doc1.source_url = None
        doc1.title = "Doc A"
        doc1.owner = None
        doc1.status = "active"
        doc1.content_hash = "a"
        doc1.last_synced_at = None
        doc1.created_at = now
        doc1.updated_at = now

        doc2 = Mock()
        doc2.id = uuid.uuid4()
        doc2.source_type = "markdown"
        doc2.source_id = "/b.md"
        doc2.source_url = None
        doc2.title = "Doc B"
        doc2.owner = None
        doc2.status = "active"
        doc2.content_hash = "b"
        doc2.last_synced_at = None
        doc2.created_at = now - timedelta(seconds=1)
        doc2.updated_at = now - timedelta(seconds=1)

        doc3 = Mock()
        doc3.id = uuid.uuid4()
        doc3.source_type = "markdown"
        doc3.source_id = "/c.md"
        doc3.source_url = None
        doc3.title = "Doc C"
        doc3.owner = None
        doc3.status = "active"
        doc3.content_hash = "c"
        doc3.last_synced_at = None
        doc3.created_at = now - timedelta(seconds=2)
        doc3.updated_at = now - timedelta(seconds=2)

        # First request: count + docs (limit=2, returns 3 rows to detect next page)
        count1 = Mock()
        count1.scalar.return_value = 3
        page1_result = Mock()
        page1_result.all.return_value = [(doc1, 1), (doc2, 2), (doc3, 0)]

        mock_api_db_session.execute = AsyncMock(side_effect=[count1, page1_result])

        resp1 = await client.get("/api/documents?limit=2")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["items"]) == 2
        assert data1["cursor"] != ""  # has more pages
        page1_ids = {item["id"] for item in data1["items"]}

        # Second request: use cursor from page 1
        count2 = Mock()
        count2.scalar.return_value = 3
        page2_result = Mock()
        page2_result.all.return_value = [(doc3, 0)]

        mock_api_db_session.execute = AsyncMock(side_effect=[count2, page2_result])

        resp2 = await client.get(f"/api/documents?limit=2&cursor={data1['cursor']}")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) == 1
        assert data2["cursor"] == ""  # last page
        page2_ids = {item["id"] for item in data2["items"]}

        # No overlap between pages
        assert page1_ids.isdisjoint(page2_ids)


class TestAdminUserPagination:
    """Test pagination on /admin/users endpoint."""

    async def test_returns_paginated_envelope(self, client, mock_api_db_session):
        from pam.common.models import User

        user = User(
            id=uuid.uuid4(),
            email="user@test.com",
            name="Test",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        count_result = Mock()
        count_result.scalar.return_value = 1

        user_result = Mock()
        user_scalars = Mock()
        user_scalars.all.return_value = [user]
        user_result.scalars.return_value = user_scalars

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, user_result])

        response = await client.get("/api/admin/users?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "cursor" in data
        assert data["total"] == 1


class TestIngestTaskPagination:
    """Test pagination on /ingest/tasks endpoint."""

    async def test_returns_paginated_envelope(self, client, mock_api_db_session):
        count_result = Mock()
        count_result.scalar.return_value = 0

        task_result = Mock()
        task_scalars = Mock()
        task_scalars.all.return_value = []
        task_result.scalars.return_value = task_scalars

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, task_result])

        response = await client.get("/api/ingest/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["cursor"] == ""
