"""Integration test for GitHubConnector against a real public repo.

Requires: gh CLI installed and authenticated (gh auth login).
Run with: pytest tests/integration/ -m integration -v
"""

import pytest

from pam.ingestion.connectors.github import GitHubConnector


@pytest.mark.integration
class TestGitHubIntegration:
    """Tests against a small, stable public repo (github/gitignore)."""

    async def test_list_documents_returns_files(self):
        connector = GitHubConnector(
            repo="github/gitignore",
            branch="main",
            extensions=[".gitignore"],
        )
        available = await connector.check_available()
        if not available:
            pytest.skip("gh CLI not available")

        docs = await connector.list_documents()
        assert len(docs) > 0
        assert all(d.source_id.startswith("github/gitignore:") for d in docs)

    async def test_fetch_document_returns_content(self):
        connector = GitHubConnector(
            repo="github/gitignore",
            branch="main",
            paths=[""],
            extensions=[".gitignore"],
        )
        available = await connector.check_available()
        if not available:
            pytest.skip("gh CLI not available")

        docs = await connector.list_documents()
        assert len(docs) > 0

        doc = await connector.fetch_document(docs[0].source_id)
        assert len(doc.content) > 0
        assert doc.content_type == "text/plain"

    async def test_content_hash_uses_cached_sha(self):
        connector = GitHubConnector(
            repo="github/gitignore",
            branch="main",
            extensions=[".gitignore"],
        )
        available = await connector.check_available()
        if not available:
            pytest.skip("gh CLI not available")

        docs = await connector.list_documents()
        assert len(docs) > 0

        sha = await connector.get_content_hash(docs[0].source_id)
        assert len(sha) == 40  # Git SHA-1 is 40 hex chars
