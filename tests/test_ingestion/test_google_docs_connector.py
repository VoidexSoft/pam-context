"""Tests for Google Docs connector."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.google_docs import (
    DOCX_MIME,
    GOOGLE_DOC_MIME,
    GoogleDocsConnector,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_drive_file(
    file_id: str = "doc1",
    name: str = "Test Doc",
    owner_email: str | None = "alice@example.com",
    web_view_link: str = "https://docs.google.com/document/d/doc1",
    modified_time: str = "2024-06-01T12:00:00.000Z",
):
    """Build a fake Drive API file resource."""
    f = {
        "id": file_id,
        "name": name,
        "webViewLink": web_view_link,
        "modifiedTime": modified_time,
    }
    if owner_email is not None:
        f["owners"] = [{"emailAddress": owner_email}]
    return f


def _mock_execute(return_value):
    """Return a mock request object whose .execute() returns *return_value*."""
    req = MagicMock()
    req.execute.return_value = return_value
    return req


def _make_sync_loop():
    """Create a mock event loop that runs executor functions synchronously."""
    loop = MagicMock()
    loop.run_in_executor = AsyncMock(side_effect=lambda _, fn: fn())
    return loop


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def connector():
    """GoogleDocsConnector with a fake credentials path and one folder."""
    return GoogleDocsConnector(
        credentials_path="/fake/creds.json",
        folder_ids=["folder_a"],
    )


@pytest.fixture
def connector_multi():
    """GoogleDocsConnector with two folders."""
    return GoogleDocsConnector(
        credentials_path="/fake/creds.json",
        folder_ids=["folder_a", "folder_b"],
    )


@pytest.fixture
def mock_service():
    """A fully-wired mock Drive v3 service."""
    service = MagicMock()
    service.files.return_value = service
    return service


@pytest.fixture
def patch_loop():
    """Patch asyncio.get_running_loop to return a synchronous executor."""
    loop = _make_sync_loop()
    with patch(
        "pam.ingestion.connectors.google_docs.asyncio.get_running_loop",
        return_value=loop,
    ):
        yield loop


# ── _get_service tests ────────────────────────────────────────────────


class TestGetService:
    def test_raises_when_no_credentials_path(self):
        conn = GoogleDocsConnector(credentials_path=None, folder_ids=[])
        with pytest.raises(ValueError, match="Google credentials path required"):
            conn._get_service()

    def test_returns_cached_service_on_second_call(self):
        """Second call returns the cached object without rebuilding."""
        conn = GoogleDocsConnector(credentials_path="/fake/creds.json", folder_ids=[])
        sentinel = MagicMock(name="cached_service")
        conn._service = sentinel

        result = conn._get_service()
        assert result is sentinel

    def test_builds_drive_service_from_credentials(self):
        """Imports, loads creds, and calls build() on first access."""
        fake_creds = MagicMock(name="credentials")
        fake_service = MagicMock(name="drive_service")

        with patch.dict(
            "sys.modules",
            {
                "google": MagicMock(),
                "google.oauth2": MagicMock(),
                "google.oauth2.credentials": MagicMock(
                    Credentials=MagicMock(
                        from_authorized_user_file=MagicMock(return_value=fake_creds)
                    )
                ),
                "googleapiclient": MagicMock(),
                "googleapiclient.discovery": MagicMock(
                    build=MagicMock(return_value=fake_service)
                ),
            },
        ):
            conn = GoogleDocsConnector(credentials_path="/fake/creds.json", folder_ids=[])
            result = conn._get_service()
            assert result is fake_service
            assert conn._service is fake_service


# ── list_documents tests ──────────────────────────────────────────────


class TestListDocuments:
    async def test_returns_docs_from_multiple_folders(
        self, connector_multi, mock_service, patch_loop
    ):
        """Documents from two folders should be combined."""
        files_a = [_make_drive_file("a1", "Doc A1"), _make_drive_file("a2", "Doc A2")]
        files_b = [_make_drive_file("b1", "Doc B1")]

        list_req = MagicMock()
        list_req.execute = MagicMock(
            side_effect=[{"files": files_a}, {"files": files_b}]
        )
        mock_service.list.return_value = list_req
        connector_multi._service = mock_service

        docs = await connector_multi.list_documents()

        assert len(docs) == 3
        ids = {d.source_id for d in docs}
        assert ids == {"a1", "a2", "b1"}
        for d in docs:
            assert isinstance(d, DocumentInfo)
            assert d.owner == "alice@example.com"

    async def test_handles_empty_results(self, connector, mock_service, patch_loop):
        """Folder with no docs should return an empty list."""
        mock_service.list.return_value = _mock_execute({"files": []})
        connector._service = mock_service

        docs = await connector.list_documents()
        assert docs == []

    async def test_handles_missing_owners_field(
        self, connector, mock_service, patch_loop
    ):
        """Files without an 'owners' key should have owner=None."""
        file_no_owner = _make_drive_file(owner_email=None)
        file_no_owner.pop("owners", None)

        mock_service.list.return_value = _mock_execute({"files": [file_no_owner]})
        connector._service = mock_service

        docs = await connector.list_documents()
        assert len(docs) == 1
        assert docs[0].owner is None

    async def test_handles_empty_owners_list(
        self, connector, mock_service, patch_loop
    ):
        """Files with an empty 'owners' list should have owner=None."""
        file_data = _make_drive_file()
        file_data["owners"] = []

        mock_service.list.return_value = _mock_execute({"files": [file_data]})
        connector._service = mock_service

        docs = await connector.list_documents()
        assert len(docs) == 1
        assert docs[0].owner is None

    async def test_populates_source_url(self, connector, mock_service, patch_loop):
        """webViewLink should map to source_url."""
        url = "https://docs.google.com/document/d/xyz"
        file_data = _make_drive_file(web_view_link=url)

        mock_service.list.return_value = _mock_execute({"files": [file_data]})
        connector._service = mock_service

        docs = await connector.list_documents()
        assert docs[0].source_url == url

    async def test_correct_query_per_folder(
        self, connector, mock_service, patch_loop
    ):
        """Verify the Drive query string includes folder ID and mime type."""
        mock_service.list.return_value = _mock_execute({"files": []})
        connector._service = mock_service

        await connector.list_documents()

        call_kwargs = mock_service.list.call_args
        query = call_kwargs.kwargs.get("q", "") or call_kwargs[1].get("q", "")
        assert "folder_a" in query
        assert GOOGLE_DOC_MIME in query
        assert "trashed=false" in query

    async def test_no_folders_returns_empty(self, patch_loop):
        """Connector with zero folders should return empty list immediately."""
        conn = GoogleDocsConnector(credentials_path="/fake/creds.json", folder_ids=[])
        # Pre-set a service so _get_service doesn't try to import google libs
        conn._service = MagicMock()

        docs = await conn.list_documents()
        assert docs == []


# ── fetch_document tests ──────────────────────────────────────────────


class TestFetchDocument:
    async def test_returns_raw_document_with_correct_fields(
        self, connector, mock_service, patch_loop
    ):
        content_bytes = b"fake docx bytes"
        meta = _make_drive_file("doc42", "My Document")

        mock_service.get.return_value = _mock_execute(meta)
        mock_service.export.return_value = _mock_execute(content_bytes)
        connector._service = mock_service

        doc = await connector.fetch_document("doc42")

        assert isinstance(doc, RawDocument)
        assert doc.source_id == "doc42"
        assert doc.title == "My Document"
        assert doc.content == content_bytes
        assert doc.content_type == DOCX_MIME
        assert doc.owner == "alice@example.com"
        assert doc.source_url == "https://docs.google.com/document/d/doc1"

    async def test_handles_missing_owner(
        self, connector, mock_service, patch_loop
    ):
        meta = _make_drive_file(owner_email=None)
        meta.pop("owners", None)

        mock_service.get.return_value = _mock_execute(meta)
        mock_service.export.return_value = _mock_execute(b"docx")
        connector._service = mock_service

        doc = await connector.fetch_document("doc1")
        assert doc.owner is None

    async def test_export_uses_docx_mime(
        self, connector, mock_service, patch_loop
    ):
        """Export should request DOCX mime type."""
        mock_service.get.return_value = _mock_execute(_make_drive_file())
        mock_service.export.return_value = _mock_execute(b"data")
        connector._service = mock_service

        await connector.fetch_document("doc1")

        mock_service.export.assert_called_once_with(
            fileId="doc1", mimeType=DOCX_MIME
        )

    async def test_requests_correct_metadata_fields(
        self, connector, mock_service, patch_loop
    ):
        mock_service.get.return_value = _mock_execute(_make_drive_file())
        mock_service.export.return_value = _mock_execute(b"data")
        connector._service = mock_service

        await connector.fetch_document("doc1")

        mock_service.get.assert_called_once_with(
            fileId="doc1", fields="name, owners, webViewLink"
        )


# ── get_content_hash tests ───────────────────────────────────────────


class TestGetContentHash:
    async def test_returns_md5_when_available(
        self, connector, mock_service, patch_loop
    ):
        expected_md5 = "d41d8cd98f00b204e9800998ecf8427e"
        mock_service.get.return_value = _mock_execute(
            {"md5Checksum": expected_md5}
        )
        connector._service = mock_service

        result = await connector.get_content_hash("doc1")
        assert result == expected_md5

    async def test_falls_back_to_sha256_when_no_md5(
        self, connector, mock_service, patch_loop
    ):
        content = b"fake docx content for hashing"
        expected_hash = hashlib.sha256(content).hexdigest()

        mock_service.get.return_value = _mock_execute({})
        mock_service.export.return_value = _mock_execute(content)
        connector._service = mock_service

        result = await connector.get_content_hash("doc1")
        assert result == expected_hash
        assert len(result) == 64  # SHA-256 hex length

    async def test_falls_back_when_md5_is_none(
        self, connector, mock_service, patch_loop
    ):
        content = b"some bytes"
        expected_hash = hashlib.sha256(content).hexdigest()

        mock_service.get.return_value = _mock_execute({"md5Checksum": None})
        mock_service.export.return_value = _mock_execute(content)
        connector._service = mock_service

        result = await connector.get_content_hash("doc1")
        assert result == expected_hash

    async def test_export_not_called_when_md5_present(
        self, connector, mock_service, patch_loop
    ):
        """When md5Checksum is available, no export should happen."""
        mock_service.get.return_value = _mock_execute(
            {"md5Checksum": "abc123"}
        )
        connector._service = mock_service

        await connector.get_content_hash("doc1")

        mock_service.export.assert_not_called()

    async def test_sha256_fallback_exports_as_docx(
        self, connector, mock_service, patch_loop
    ):
        """Fallback path should export with DOCX mime."""
        mock_service.get.return_value = _mock_execute({})
        mock_service.export.return_value = _mock_execute(b"bytes")
        connector._service = mock_service

        await connector.get_content_hash("doc1")

        mock_service.export.assert_called_once_with(
            fileId="doc1", mimeType=DOCX_MIME
        )


# ── Constructor tests ─────────────────────────────────────────────────


class TestConstructor:
    def test_defaults(self):
        conn = GoogleDocsConnector()
        assert conn.folder_ids == []
        assert conn._service is None
        assert conn._credentials_path is None

    def test_accepts_path_object(self):
        p = Path("/some/creds.json")
        conn = GoogleDocsConnector(credentials_path=p, folder_ids=["f1"])
        assert conn._credentials_path is p
        assert conn.folder_ids == ["f1"]

    def test_accepts_string_path(self):
        conn = GoogleDocsConnector(credentials_path="/some/creds.json")
        assert conn._credentials_path == "/some/creds.json"
