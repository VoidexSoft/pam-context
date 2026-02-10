"""Tests for PostgresStore — document and segment storage."""

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pam.common.models import KnowledgeSegment
from pam.ingestion.stores.postgres_store import PostgresStore


class TestUpsertDocument:
    async def test_upsert_returns_uuid(self, mock_db_session):
        doc_id = uuid.uuid4()
        mock_result = Mock()
        mock_result.scalar_one.return_value = doc_id
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Patch the insert to return a chainable mock
        with patch("pam.ingestion.stores.postgres_store.insert") as mock_insert:
            mock_stmt = MagicMock()
            mock_insert.return_value = mock_stmt
            mock_stmt.values.return_value = mock_stmt
            mock_stmt.on_conflict_on_constraint.return_value = mock_stmt
            mock_stmt.do_update.return_value = mock_stmt
            mock_stmt.returning.return_value = mock_stmt

            store = PostgresStore(mock_db_session)
            result = await store.upsert_document(
                source_type="markdown",
                source_id="/test.md",
                title="Test",
                content_hash="abc123",
            )
            assert result == doc_id
            mock_db_session.execute.assert_called_once()
            mock_db_session.flush.assert_called_once()

    async def test_upsert_with_optional_fields(self, mock_db_session):
        doc_id = uuid.uuid4()
        mock_result = Mock()
        mock_result.scalar_one.return_value = doc_id
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch("pam.ingestion.stores.postgres_store.insert") as mock_insert:
            mock_stmt = MagicMock()
            mock_insert.return_value = mock_stmt
            mock_stmt.values.return_value = mock_stmt
            mock_stmt.on_conflict_on_constraint.return_value = mock_stmt
            mock_stmt.do_update.return_value = mock_stmt
            mock_stmt.returning.return_value = mock_stmt

            store = PostgresStore(mock_db_session)
            result = await store.upsert_document(
                source_type="google_doc",
                source_id="doc-abc",
                title="Google Doc",
                content_hash="xyz",
                source_url="https://docs.google.com/d/abc",
                owner="user@example.com",
                project_id=uuid.uuid4(),
            )
            assert result == doc_id


class TestSaveSegments:
    async def test_save_segments(self, mock_db_session):
        doc_id = uuid.uuid4()
        segments = [
            KnowledgeSegment(
                content=f"Segment {i}",
                content_hash=f"hash{i}",
                source_type="markdown",
                source_id="/test.md",
                position=i,
                document_id=doc_id,
            )
            for i in range(3)
        ]

        store = PostgresStore(mock_db_session)
        count = await store.save_segments(doc_id, segments)
        assert count == 3
        # Should delete old + add new
        mock_db_session.execute.assert_called_once()  # delete
        assert mock_db_session.add.call_count == 3

    async def test_save_empty_segments(self, mock_db_session):
        doc_id = uuid.uuid4()
        store = PostgresStore(mock_db_session)
        count = await store.save_segments(doc_id, [])
        assert count == 0


class TestLogSync:
    async def test_log_sync(self, mock_db_session):
        store = PostgresStore(mock_db_session)
        await store.log_sync(
            document_id=uuid.uuid4(),
            action="created",
            segments_affected=5,
            details={"source": "test"},
        )
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()


class TestGetDocumentBySource:
    async def test_returns_document(self, mock_db_session):
        mock_doc = Mock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_doc
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        store = PostgresStore(mock_db_session)
        result = await store.get_document_by_source("markdown", "/test.md")
        assert result is mock_doc

    async def test_returns_none_when_not_found(self, mock_db_session):
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        store = PostgresStore(mock_db_session)
        result = await store.get_document_by_source("markdown", "/nonexistent.md")
        assert result is None


class TestListDocuments:
    async def test_list_documents(self, mock_db_session):
        mock_doc = Mock()
        mock_doc.id = uuid.uuid4()
        mock_doc.source_type = "markdown"
        mock_doc.source_id = "/test.md"
        mock_doc.source_url = None
        mock_doc.title = "Test"
        mock_doc.owner = None
        mock_doc.status = "active"
        mock_doc.content_hash = "abc"
        mock_doc.last_synced_at = None
        mock_doc.created_at = None

        mock_result = Mock()
        mock_result.all.return_value = [(mock_doc, 3)]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        store = PostgresStore(mock_db_session)
        docs = await store.list_documents()
        assert len(docs) == 1
        assert docs[0]["title"] == "Test"
        assert docs[0]["segment_count"] == 3

    async def test_list_empty(self, mock_db_session):
        mock_result = Mock()
        mock_result.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        store = PostgresStore(mock_db_session)
        docs = await store.list_documents()
        assert docs == []
