"""Tests for GWS Docs CLI connector."""

import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.gws_docs import GwsDocsConnector

DRIVE_LIST_RESPONSE = {
    "files": [
        {
            "id": "doc1",
            "name": "Design Doc",
            "webViewLink": "https://docs.google.com/doc1",
            "modifiedTime": "2024-06-01T12:00:00Z",
        },
        {
            "id": "doc2",
            "name": "Meeting Notes",
            "webViewLink": "https://docs.google.com/doc2",
            "modifiedTime": "2024-07-01T10:00:00Z",
        },
    ],
}


@pytest.fixture
def connector():
    return GwsDocsConnector(folder_ids=["folder_abc"])


class TestListDocuments:
    async def test_returns_documents_from_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock, return_value=DRIVE_LIST_RESPONSE):
            docs = await connector.list_documents()

        assert len(docs) == 2
        assert all(isinstance(d, DocumentInfo) for d in docs)
        assert docs[0].source_id == "doc1"
        assert docs[0].title == "Design Doc"
        assert docs[0].source_url == "https://docs.google.com/doc1"

    async def test_handles_empty_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock, return_value={"files": []}):
            docs = await connector.list_documents()
        assert docs == []

    async def test_multiple_folders(self):
        connector = GwsDocsConnector(folder_ids=["f1", "f2"])
        responses = [
            {"files": [{"id": "d1", "name": "D1", "webViewLink": "url1", "modifiedTime": "2024-01-01T00:00:00Z"}]},
            {"files": [{"id": "d2", "name": "D2", "webViewLink": "url2", "modifiedTime": "2024-01-01T00:00:00Z"}]},
        ]
        with patch.object(connector, "run_cli", new_callable=AsyncMock, side_effect=responses):
            docs = await connector.list_documents()
        assert len(docs) == 2


class TestFetchDocument:
    async def test_exports_as_docx(self, connector):
        docx_bytes = b"fake docx content"
        with (
            patch.object(connector, "run_cli", new_callable=AsyncMock, return_value={"name": "Design Doc"}),
            patch.object(connector, "run_cli_raw", new_callable=AsyncMock, return_value=docx_bytes),
        ):
            doc = await connector.fetch_document("doc1")

        assert isinstance(doc, RawDocument)
        assert doc.content == docx_bytes
        assert doc.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert doc.source_id == "doc1"
        assert doc.title == "Design Doc"

    async def test_calls_export_api(self, connector):
        mock_raw = AsyncMock(return_value=b"bytes")
        with (
            patch.object(connector, "run_cli", new_callable=AsyncMock, return_value={"name": "Doc"}),
            patch.object(connector, "run_cli_raw", mock_raw),
        ):
            await connector.fetch_document("doc123")
        args = mock_raw.call_args[0][0]
        assert "export" in " ".join(args)
        assert "doc123" in " ".join(args)

    async def test_falls_back_to_source_id_when_name_missing(self, connector):
        with (
            patch.object(connector, "run_cli", new_callable=AsyncMock, return_value={}),
            patch.object(connector, "run_cli_raw", new_callable=AsyncMock, return_value=b"bytes"),
        ):
            doc = await connector.fetch_document("doc1")
        assert doc.title == "doc1"


class TestGetContentHash:
    async def test_returns_md5_from_api(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock, return_value={"md5Checksum": "abc123hash"}):
            result = await connector.get_content_hash("doc1")
        assert result == "abc123hash"

    async def test_falls_back_to_sha256(self, connector):
        content = b"exported docx"
        with (
            patch.object(connector, "run_cli", new_callable=AsyncMock, return_value={}),
            patch.object(connector, "run_cli_raw", new_callable=AsyncMock, return_value=content),
        ):
            result = await connector.get_content_hash("doc1")
        assert result == hashlib.sha256(content).hexdigest()
