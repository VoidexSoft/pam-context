"""Tests for POST /api/ingest/folder endpoint."""

from unittest.mock import AsyncMock, patch

from pam.ingestion.pipeline import IngestionResult


class TestIngestEndpoint:
    @patch("pam.api.routes.ingest.IngestionPipeline")
    @patch("pam.api.routes.ingest.ElasticsearchStore")
    @patch("pam.api.routes.ingest.DoclingParser")
    @patch("pam.api.routes.ingest.MarkdownConnector")
    async def test_ingest_success(
        self, mock_connector_cls, mock_parser_cls, mock_es_cls, mock_pipeline_cls, client, tmp_path
    ):
        # Create a real temp directory
        (tmp_path / "doc.md").write_text("# Test")

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_all = AsyncMock(
            return_value=[IngestionResult(source_id=str(tmp_path / "doc.md"), title="doc", segments_created=5)]
        )
        mock_pipeline_cls.return_value = mock_pipeline

        response = await client.post(
            "/api/ingest/folder",
            json={"path": str(tmp_path)},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["succeeded"] == 1
        assert data["failed"] == 0

    async def test_ingest_invalid_path(self, client):
        response = await client.post(
            "/api/ingest/folder",
            json={"path": "/nonexistent/path"},
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower() or "Directory" in response.json()["detail"]
