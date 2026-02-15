"""Tests for MarkdownConnector — local markdown file ingestion."""

import hashlib

import pytest

from pam.ingestion.connectors.markdown import MarkdownConnector


class TestMarkdownConnectorInit:
    def test_valid_directory(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        assert connector.directory == temp_dir.resolve()

    def test_invalid_directory(self):
        with pytest.raises(ValueError, match="Directory does not exist"):
            MarkdownConnector("/nonexistent/path")

    def test_accepts_string_path(self, temp_dir):
        connector = MarkdownConnector(str(temp_dir))
        assert connector.directory == temp_dir.resolve()


class TestListDocuments:
    async def test_lists_markdown_files(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        docs = await connector.list_documents()
        titles = {d.title for d in docs}
        assert "doc1" in titles
        assert "doc2" in titles
        assert "doc3" in titles  # nested file

    async def test_excludes_non_markdown(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        docs = await connector.list_documents()
        source_ids = {d.source_id for d in docs}
        assert not any("not_markdown" in sid for sid in source_ids)

    async def test_empty_directory(self, tmp_path):
        connector = MarkdownConnector(tmp_path)
        docs = await connector.list_documents()
        assert docs == []

    async def test_document_has_source_url(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        docs = await connector.list_documents()
        for doc in docs:
            assert doc.source_url.startswith("file://")


class TestFetchDocument:
    async def test_fetch_existing_file(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        docs = await connector.list_documents()
        raw = await connector.fetch_document(docs[0].source_id)
        assert raw.content_type == "text/markdown"
        assert len(raw.content) > 0
        assert raw.source_url.startswith("file://")

    async def test_fetch_nonexistent_file(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        with pytest.raises(FileNotFoundError):
            await connector.fetch_document(str(temp_dir / "nonexistent.md"))

    async def test_fetch_path_traversal_denied(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        with pytest.raises(ValueError, match="Path traversal denied"):
            await connector.fetch_document("/etc/passwd")


class TestContentHash:
    async def test_returns_sha256(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        docs = await connector.list_documents()
        hash_ = await connector.get_content_hash(docs[0].source_id)
        # Verify it matches actual file content hash
        content = open(docs[0].source_id, "rb").read()
        expected = hashlib.sha256(content).hexdigest()
        assert hash_ == expected

    async def test_hash_changes_on_content_change(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        docs = await connector.list_documents()
        hash1 = await connector.get_content_hash(docs[0].source_id)
        # Modify the file
        with open(docs[0].source_id, "a") as f:
            f.write("\nNew content")
        hash2 = await connector.get_content_hash(docs[0].source_id)
        assert hash1 != hash2

    async def test_content_hash_path_traversal_denied(self, temp_dir):
        connector = MarkdownConnector(temp_dir)
        with pytest.raises(ValueError, match="Path traversal denied"):
            await connector.get_content_hash("/etc/passwd")
