"""Tests for ingest endpoints — POST /api/ingest/folder, GET /api/ingest/tasks."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pam.api.routes.ingest import _segment_to_knowledge_segment
from pam.common.models import IngestionTask


class TestIngestEndpoint:
    @patch("pam.api.routes.ingest.settings")
    @patch("pam.api.routes.ingest.spawn_ingestion_task")
    @patch("pam.api.routes.ingest.create_task")
    async def test_ingest_returns_202(self, mock_create, mock_spawn, mock_settings, client, tmp_path):
        (tmp_path / "doc.md").write_text("# Test")
        mock_settings.ingest_root = str(tmp_path)

        task_id = uuid.uuid4()
        mock_task = MagicMock(spec=IngestionTask)
        mock_task.id = task_id
        mock_create.return_value = mock_task

        response = await client.post(
            "/api/ingest/folder",
            json={"path": str(tmp_path)},
        )
        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == str(task_id)
        assert data["status"] == "pending"
        mock_spawn.assert_called_once()

    @patch("pam.api.routes.ingest.settings")
    async def test_ingest_invalid_path(self, mock_settings, client, tmp_path):
        mock_settings.ingest_root = str(tmp_path)
        nonexistent = str(tmp_path / "does_not_exist")
        response = await client.post(
            "/api/ingest/folder",
            json={"path": nonexistent},
        )
        assert response.status_code == 400

    @patch("pam.api.routes.ingest.settings")
    async def test_ingest_root_not_configured(self, mock_settings, client, tmp_path):
        mock_settings.ingest_root = ""
        response = await client.post(
            "/api/ingest/folder",
            json={"path": str(tmp_path)},
        )
        assert response.status_code == 400
        assert "not configured" in response.json()["detail"]

    @patch("pam.api.routes.ingest.settings")
    async def test_ingest_path_outside_root(self, mock_settings, client, tmp_path):
        mock_settings.ingest_root = str(tmp_path / "allowed")
        response = await client.post(
            "/api/ingest/folder",
            json={"path": "/etc"},
        )
        assert response.status_code == 403
        assert "outside" in response.json()["detail"]

    @patch("pam.api.routes.ingest.settings")
    async def test_ingest_path_traversal_rejected(self, mock_settings, client, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        mock_settings.ingest_root = str(allowed)
        response = await client.post(
            "/api/ingest/folder",
            json={"path": str(allowed / ".." / "other")},
        )
        assert response.status_code == 403

    @patch("pam.api.routes.ingest.get_task")
    async def test_get_task_found(self, mock_get_task, client):
        from datetime import datetime

        task_id = uuid.uuid4()
        mock_task = MagicMock(spec=IngestionTask)
        mock_task.id = task_id
        mock_task.status = "running"
        mock_task.folder_path = "/tmp/docs"
        mock_task.total_documents = 5
        mock_task.processed_documents = 2
        mock_task.succeeded = 2
        mock_task.skipped = 0
        mock_task.failed = 0
        mock_task.results = []
        mock_task.error = None
        mock_task.created_at = datetime.now(UTC)
        mock_task.started_at = datetime.now(UTC)
        mock_task.completed_at = None
        mock_get_task.return_value = mock_task

        response = await client.get(f"/api/ingest/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["total_documents"] == 5
        assert data["processed_documents"] == 2

    @patch("pam.api.routes.ingest.get_task")
    async def test_get_task_not_found(self, mock_get_task, client):
        mock_get_task.return_value = None
        response = await client.get(f"/api/ingest/tasks/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_list_tasks(self, client, mock_api_db_session):
        # First call: count query
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Second call: tasks query
        task_result = MagicMock()
        task_scalars = MagicMock()
        task_scalars.all.return_value = []
        task_result.scalars.return_value = task_scalars

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, task_result])

        response = await client.get("/api/ingest/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["cursor"] == ""

    async def test_list_tasks_invalid_cursor_returns_400(self, client):
        """Invalid base64 cursor → 400 with 'Invalid cursor' (B904 exception chaining)."""
        response = await client.get("/api/ingest/tasks?cursor=not-valid-base64!!!")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid cursor"


class TestSegmentToKnowledgeSegment:
    """Phase 10: Test the pure _segment_to_knowledge_segment converter."""

    def test_converts_orm_segment_fields(self):
        """Maps ORM Segment fields to KnowledgeSegment correctly."""
        seg = Mock()
        seg.id = uuid.uuid4()
        seg.content = "Some content"
        seg.content_hash = "abc123"
        seg.segment_type = "text"
        seg.section_path = "Section > Sub"
        seg.position = 3
        seg.metadata_ = {"graph_episode_uuid": "ep-1"}

        ks = _segment_to_knowledge_segment(seg)

        assert ks.id == seg.id
        assert ks.content == "Some content"
        assert ks.content_hash == "abc123"
        assert ks.segment_type == "text"
        assert ks.section_path == "Section > Sub"
        assert ks.position == 3
        assert ks.metadata == {"graph_episode_uuid": "ep-1"}

    def test_handles_none_metadata(self):
        """When metadata_ is None, defaults to empty dict."""
        seg = Mock()
        seg.id = uuid.uuid4()
        seg.content = "text"
        seg.content_hash = "h"
        seg.segment_type = "text"
        seg.section_path = None
        seg.position = 0
        seg.metadata_ = None

        ks = _segment_to_knowledge_segment(seg)
        assert ks.metadata == {}


class TestSyncGraphEndpoint:
    """Phase 10: Test sync-graph endpoint reference_time cascading fallback."""

    @patch("pam.api.routes.ingest.rollback_graph_for_document")
    @patch("pam.api.routes.ingest.extract_graph_for_document")
    @patch("pam.api.routes.ingest.PostgresStore")
    async def test_sync_graph_uses_modified_at_as_reference_time(
        self, mock_pg_cls, mock_extract, mock_rollback, client, mock_api_db_session
    ):
        """doc.modified_at is used as primary reference_time in sync-graph."""
        ts = datetime(2024, 5, 20, 14, 0, 0, tzinfo=UTC)
        mock_doc = Mock()
        mock_doc.id = uuid.uuid4()
        mock_doc.title = "Test"
        mock_doc.source_id = "/test.md"
        mock_doc.modified_at = ts
        mock_doc.last_synced_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_pg = AsyncMock()
        mock_pg.get_unsynced_documents = AsyncMock(side_effect=[[mock_doc], []])
        mock_pg.get_segments_for_document = AsyncMock(return_value=[])
        mock_pg.set_graph_synced = AsyncMock()
        mock_pg.log_sync = AsyncMock()
        mock_pg_cls.return_value = mock_pg

        mock_result = Mock()
        mock_result.entities_extracted = ["e1"]
        mock_result.diff_summary = {}
        mock_extract.return_value = mock_result

        # Override graph_service dependency to return a real mock
        from pam.api.deps import get_graph_service

        mock_graph_svc = AsyncMock()
        client._transport.app.dependency_overrides[get_graph_service] = lambda: mock_graph_svc

        response = await client.post("/api/ingest/sync-graph")
        assert response.status_code == 200

        call_kwargs = mock_extract.call_args.kwargs
        assert call_kwargs["reference_time"] == ts

    async def test_sync_graph_returns_503_without_graph_service(self, client):
        """sync-graph returns 503 when graph_service is None."""
        from pam.api.deps import get_graph_service

        client._transport.app.dependency_overrides[get_graph_service] = lambda: None

        response = await client.post("/api/ingest/sync-graph")
        assert response.status_code == 503
        assert "not available" in response.json()["detail"]
