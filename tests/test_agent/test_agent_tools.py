"""Tests for the enhanced agent tools (document context, change history, query database)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.agent.agent import RetrievalAgent
from pam.agent.duckdb_service import DuckDBService


@pytest.fixture
def mock_search_service():
    return AsyncMock()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return embedder


@pytest.fixture
def mock_session():
    return AsyncMock()


class TestGetDocumentContext:
    async def test_returns_full_document(self, mock_search_service, mock_embedder, mock_session):
        doc = MagicMock()
        doc.title = "Test Doc"
        doc.source_id = "/docs/test.md"
        doc.source_url = "file:///docs/test.md"

        seg1 = MagicMock()
        seg1.content = "First paragraph."
        seg1.position = 0
        seg2 = MagicMock()
        seg2.content = "Second paragraph."
        seg2.position = 1
        doc.segments = [seg2, seg1]  # Out of order to test sorting

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            db_session=mock_session,
        )

        result_text, citations = await agent._get_document_context({"document_title": "Test"})
        assert "First paragraph." in result_text
        assert "Second paragraph." in result_text
        assert result_text.index("First") < result_text.index("Second")
        assert len(citations) == 1
        assert citations[0].document_title == "Test Doc"

    async def test_document_not_found(self, mock_search_service, mock_embedder, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            db_session=mock_session,
        )

        result_text, citations = await agent._get_document_context({"document_title": "Nonexistent"})
        assert "not found" in result_text.lower()
        assert citations == []

    async def test_no_db_session(self, mock_search_service, mock_embedder):
        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            db_session=None,
        )

        result_text, citations = await agent._get_document_context({"document_title": "Test"})
        assert "not available" in result_text.lower()


class TestGetChangeHistory:
    async def test_returns_history(self, mock_search_service, mock_embedder, mock_session):
        from pam.common.models import SyncLog

        log1 = MagicMock(spec=SyncLog)
        log1.created_at = datetime(2025, 1, 15, tzinfo=UTC)
        log1.action = "ingest"
        log1.segments_affected = 5
        log1.details = {"source": "test.md"}

        log2 = MagicMock(spec=SyncLog)
        log2.created_at = datetime(2025, 1, 14, tzinfo=UTC)
        log2.action = "update"
        log2.segments_affected = 3
        log2.details = {}

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [log1, log2]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            db_session=mock_session,
        )

        result_text, _ = await agent._get_change_history({})
        assert "2 records" in result_text
        assert "ingest" in result_text
        assert "update" in result_text

    async def test_empty_history(self, mock_search_service, mock_embedder, mock_session):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            db_session=mock_session,
        )

        result_text, _ = await agent._get_change_history({})
        assert "no change" in result_text.lower()


class TestQueryDatabase:
    async def test_list_tables(self, mock_search_service, mock_embedder, tmp_path):
        import csv

        csv_path = tmp_path / "test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["a", "b"])
            writer.writerow([1, 2])

        duckdb_svc = DuckDBService(data_dir=str(tmp_path))
        duckdb_svc.register_files()

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            duckdb_service=duckdb_svc,
        )

        result_text, _ = await agent._query_database({"list_tables": True})
        assert "test" in result_text
        assert "Available tables" in result_text

    async def test_execute_sql(self, mock_search_service, mock_embedder, tmp_path):
        import csv

        csv_path = tmp_path / "data.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "value"])
            writer.writerow(["a", 10])
            writer.writerow(["b", 20])

        duckdb_svc = DuckDBService(data_dir=str(tmp_path))
        duckdb_svc.register_files()

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            duckdb_service=duckdb_svc,
        )

        result_text, _ = await agent._query_database({"sql": "SELECT SUM(value) as total FROM data"})
        assert "30" in result_text

    async def test_no_duckdb_service(self, mock_search_service, mock_embedder):
        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            duckdb_service=None,
        )

        result_text, _ = await agent._query_database({"sql": "SELECT 1"})
        assert "not configured" in result_text.lower()


class TestToolDispatch:
    async def test_dispatch_unknown_tool(self, mock_search_service, mock_embedder):
        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
        )

        result_text, citations = await agent._execute_tool("nonexistent_tool", {})
        assert "Unknown tool" in result_text

    async def test_dispatch_get_document_context(self, mock_search_service, mock_embedder, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            db_session=mock_session,
        )

        result_text, _ = await agent._execute_tool("get_document_context", {"document_title": "X"})
        assert "not found" in result_text.lower()

    async def test_dispatch_query_database(self, mock_search_service, mock_embedder):
        agent = RetrievalAgent(
            search_service=mock_search_service,
            embedder=mock_embedder,
            duckdb_service=None,
        )

        result_text, _ = await agent._execute_tool("query_database", {"sql": "SELECT 1"})
        assert "not configured" in result_text.lower()
