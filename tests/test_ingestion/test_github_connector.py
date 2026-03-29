"""Tests for GitHub CLI connector."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.github import GitHubConnector


# ── Helpers ──────────────────────────────────────────────────────────

TREE_RESPONSE = {
    "sha": "abc123",
    "tree": [
        {"path": "README.md", "type": "blob", "sha": "sha_readme"},
        {"path": "docs/guide.md", "type": "blob", "sha": "sha_guide"},
        {"path": "docs/api.txt", "type": "blob", "sha": "sha_api"},
        {"path": "src/main.py", "type": "blob", "sha": "sha_main"},
        {"path": "docs/images", "type": "tree", "sha": "sha_dir"},
        {"path": "docs/image.png", "type": "blob", "sha": "sha_png"},
    ],
}


@pytest.fixture
def connector():
    return GitHubConnector(repo="owner/repo", branch="main")


@pytest.fixture
def connector_filtered():
    return GitHubConnector(
        repo="owner/repo",
        branch="develop",
        paths=["docs/"],
        extensions=[".md"],
    )


# ── list_documents tests ────────────────────────────────────────────


class TestListDocuments:
    async def test_returns_md_and_txt_by_default(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector.list_documents()

        source_ids = {d.source_id for d in docs}
        assert source_ids == {
            "owner/repo:README.md",
            "owner/repo:docs/guide.md",
            "owner/repo:docs/api.txt",
        }

    async def test_filters_by_paths_and_extensions(self, connector_filtered):
        with patch.object(connector_filtered, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector_filtered.list_documents()

        source_ids = {d.source_id for d in docs}
        assert source_ids == {"owner/repo:docs/guide.md"}

    async def test_returns_document_info_fields(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector.list_documents()

        guide = next(d for d in docs if "guide" in d.source_id)
        assert isinstance(guide, DocumentInfo)
        assert guide.title == "guide.md"
        assert guide.source_url == "https://github.com/owner/repo/blob/main/docs/guide.md"

    async def test_skips_tree_entries(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector.list_documents()

        paths = {d.source_id for d in docs}
        assert not any("images" in p for p in paths)

    async def test_empty_tree(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={"tree": []}):
            docs = await connector.list_documents()
        assert docs == []

    async def test_calls_correct_api(self, connector):
        mock_run = AsyncMock(return_value={"tree": []})
        with patch.object(connector, "run_cli", mock_run):
            await connector.list_documents()
        mock_run.assert_called_once_with(
            ["api", "/repos/owner/repo/git/trees/main?recursive=1"]
        )

    async def test_populates_sha_cache(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            await connector.list_documents()

        assert connector._tree_cache["owner/repo:README.md"] == "sha_readme"
        assert connector._tree_cache["owner/repo:docs/guide.md"] == "sha_guide"


# ── get_content_hash tests ──────────────────────────────────────────


class TestGetContentHash:
    async def test_returns_cached_sha(self, connector):
        connector._tree_cache["owner/repo:README.md"] = "sha_readme"
        result = await connector.get_content_hash("owner/repo:README.md")
        assert result == "sha_readme"

    async def test_raises_when_no_cache(self, connector):
        with pytest.raises(KeyError):
            await connector.get_content_hash("owner/repo:unknown.md")


# ── fetch_document tests ────────────────────────────────────────────


class TestFetchDocument:
    async def test_returns_raw_document_for_markdown(self, connector):
        content = b"# Hello World\n\nSome content."
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=content):
            doc = await connector.fetch_document("owner/repo:docs/guide.md")

        assert isinstance(doc, RawDocument)
        assert doc.content == content
        assert doc.content_type == "text/markdown"
        assert doc.source_id == "owner/repo:docs/guide.md"
        assert doc.title == "guide.md"
        assert doc.source_url == "https://github.com/owner/repo/blob/main/docs/guide.md"

    async def test_returns_plain_text_for_txt(self, connector):
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=b"plain text"):
            doc = await connector.fetch_document("owner/repo:notes.txt")

        assert doc.content_type == "text/plain"

    async def test_calls_correct_api_with_raw_accept(self, connector):
        mock_raw = AsyncMock(return_value=b"content")
        with patch.object(connector, "run_cli_raw", mock_raw):
            await connector.fetch_document("owner/repo:docs/guide.md")

        mock_raw.assert_called_once_with([
            "api", "/repos/owner/repo/contents/docs/guide.md?ref=main",
            "-H", "Accept: application/vnd.github.raw+json",
        ])

    async def test_handles_nested_path(self, connector):
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=b"deep"):
            doc = await connector.fetch_document("owner/repo:a/b/c/file.md")

        assert doc.title == "file.md"
        assert "a/b/c/file.md" in doc.source_url
