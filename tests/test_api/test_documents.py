"""Tests for GET /api/documents, /api/segments, and /api/stats endpoints."""

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


class TestSegmentEndpoint:
    async def test_get_segment_success(self, client, mock_api_db_session):
        """GET /api/segments/{id} returns segment with parent document info."""
        seg_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        mock_segment = Mock()
        mock_segment.id = seg_id
        mock_segment.content = "Revenue was $10M in Q1."
        mock_segment.segment_type = "text"
        mock_segment.section_path = "Financials > Revenue"
        mock_segment.position = 3
        mock_segment.metadata_ = {"source": "annual_report"}
        mock_segment.document_id = doc_id

        mock_doc = Mock()
        mock_doc.id = doc_id
        mock_doc.title = "Annual Report 2024"
        mock_doc.source_url = "http://example.com/report.pdf"
        mock_doc.source_type = "pdf"

        # db.execute is called twice: once for Segment, once for Document
        seg_result = Mock()
        seg_result.scalar_one_or_none.return_value = mock_segment

        doc_result = Mock()
        doc_result.scalar_one_or_none.return_value = mock_doc

        mock_api_db_session.execute = AsyncMock(side_effect=[seg_result, doc_result])

        response = await client.get(f"/api/segments/{seg_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(seg_id)
        assert data["content"] == "Revenue was $10M in Q1."
        assert data["segment_type"] == "text"
        assert data["section_path"] == "Financials > Revenue"
        assert data["position"] == 3
        assert data["document_id"] == str(doc_id)
        assert data["document_title"] == "Annual Report 2024"
        assert data["source_url"] == "http://example.com/report.pdf"
        assert data["source_type"] == "pdf"

    async def test_get_segment_not_found(self, client, mock_api_db_session):
        """GET /api/segments/{id} returns 404 when segment does not exist."""
        seg_id = uuid.uuid4()

        seg_result = Mock()
        seg_result.scalar_one_or_none.return_value = None
        mock_api_db_session.execute = AsyncMock(return_value=seg_result)

        response = await client.get(f"/api/segments/{seg_id}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Segment not found"


class TestStatsEndpoint:
    async def test_get_stats(self, client, mock_api_db_session):
        """GET /api/stats returns aggregated statistics."""
        task_id = uuid.uuid4()

        # Mock for document counts by status
        doc_count_result = Mock()
        doc_count_result.all.return_value = [("active", 5), ("archived", 2)]

        # Mock for total segment count
        seg_count_result = Mock()
        seg_count_result.scalar.return_value = 42

        # Mock for entity counts by type
        entity_count_result = Mock()
        entity_count_result.all.return_value = [("person", 10), ("org", 8)]

        # Mock for recent tasks
        mock_task = Mock()
        mock_task.id = task_id
        mock_task.status = "completed"
        mock_task.folder_path = "/data/reports"
        mock_task.total_documents = 5
        mock_task.succeeded = 4
        mock_task.failed = 1
        mock_task.created_at = None
        mock_task.completed_at = None

        task_result = Mock()
        task_scalars = Mock()
        task_scalars.all.return_value = [mock_task]
        task_result.scalars.return_value = task_scalars

        mock_api_db_session.execute = AsyncMock(
            side_effect=[doc_count_result, seg_count_result, entity_count_result, task_result]
        )

        response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()

        assert data["documents"]["total"] == 7
        assert data["documents"]["by_status"]["active"] == 5
        assert data["documents"]["by_status"]["archived"] == 2
        assert data["segments"] == 42
        assert data["entities"]["total"] == 18
        assert data["entities"]["by_type"]["person"] == 10
        assert data["entities"]["by_type"]["org"] == 8
        assert len(data["recent_tasks"]) == 1
        assert data["recent_tasks"][0]["status"] == "completed"
        assert data["recent_tasks"][0]["folder_path"] == "/data/reports"
