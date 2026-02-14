"""Tests for ingest endpoints — POST /api/ingest/folder, GET /api/ingest/tasks."""

import uuid
from datetime import UTC
from unittest.mock import MagicMock, patch

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

    async def test_ingest_invalid_path(self, client):
        response = await client.post(
            "/api/ingest/folder",
            json={"path": "/nonexistent/path"},
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

    @patch("pam.api.routes.ingest.list_tasks")
    async def test_list_tasks(self, mock_list, client):
        mock_list.return_value = []
        response = await client.get("/api/ingest/tasks")
        assert response.status_code == 200
        assert response.json() == []
