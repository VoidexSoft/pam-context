"""Tests for IngestionPipeline — orchestration of the full ingestion flow."""

import hashlib
import uuid
from unittest.mock import AsyncMock, Mock, patch

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.pipeline import IngestionPipeline


def _make_pipeline(
    mock_connector,
    mock_parser,
    mock_embedder,
    mock_es_store,
    mock_db_session,
):
    return IngestionPipeline(
        connector=mock_connector,
        parser=mock_parser,
        embedder=mock_embedder,
        es_store=mock_es_store,
        session=mock_db_session,
        source_type="markdown",
    )


class TestIngestDocument:
    @patch("pam.ingestion.pipeline.chunk_document")
    @patch("pam.ingestion.pipeline.PostgresStore")
    async def test_success_flow(
        self,
        mock_pg_cls,
        mock_chunk_fn,
        mock_connector,
        mock_parser,
        mock_embedder,
        mock_es_store,
        mock_db_session,
    ):
        """Full successful ingestion: fetch → parse → chunk → embed → store."""
        # Setup
        raw_doc = RawDocument(
            content=b"# Test",
            content_type="text/markdown",
            source_id="/test.md",
            title="Test",
        )
        mock_connector.fetch_document = AsyncMock(return_value=raw_doc)
        mock_connector.get_content_hash = AsyncMock(return_value="newhash")

        mock_pg = AsyncMock()
        mock_pg.get_document_by_source = AsyncMock(return_value=None)  # new doc
        doc_id = uuid.uuid4()
        mock_pg.upsert_document = AsyncMock(return_value=doc_id)
        mock_pg.save_segments = AsyncMock(return_value=2)
        mock_pg.log_sync = AsyncMock()
        mock_pg_cls.return_value = mock_pg

        mock_chunk = Mock(content="chunk", content_hash="h1", section_path=None, segment_type="text", position=0)
        mock_chunk_fn.return_value = [mock_chunk]

        mock_embedder.embed_texts_with_cache = AsyncMock(return_value=[[0.1] * 1536])

        pipeline = _make_pipeline(mock_connector, mock_parser, mock_embedder, mock_es_store, mock_db_session)
        result = await pipeline.ingest_document("/test.md")

        assert result.error is None
        assert result.skipped is False
        assert result.title == "Test"
        mock_pg.upsert_document.assert_called_once()
        mock_pg.save_segments.assert_called_once()
        mock_es_store.delete_by_document.assert_called_once()
        mock_es_store.bulk_index.assert_called_once()
        mock_db_session.commit.assert_called_once()

    @patch("pam.ingestion.pipeline.chunk_document")
    @patch("pam.ingestion.pipeline.PostgresStore")
    async def test_skip_unchanged(
        self,
        mock_pg_cls,
        mock_chunk_fn,
        mock_connector,
        mock_parser,
        mock_embedder,
        mock_es_store,
        mock_db_session,
    ):
        """Should skip documents whose content hash hasn't changed."""
        content = b"# Same"
        content_hash = hashlib.sha256(content).hexdigest()
        raw_doc = RawDocument(
            content=content,
            content_type="text/markdown",
            source_id="/same.md",
            title="Same",
        )
        mock_connector.fetch_document = AsyncMock(return_value=raw_doc)

        existing_doc = Mock()
        existing_doc.content_hash = content_hash
        mock_pg = AsyncMock()
        mock_pg.get_document_by_source = AsyncMock(return_value=existing_doc)
        mock_pg_cls.return_value = mock_pg

        pipeline = _make_pipeline(mock_connector, mock_parser, mock_embedder, mock_es_store, mock_db_session)
        result = await pipeline.ingest_document("/same.md")

        assert result.skipped is True
        assert result.segments_created == 0
        mock_parser.parse.assert_not_called()

    @patch("pam.ingestion.pipeline.chunk_document")
    @patch("pam.ingestion.pipeline.PostgresStore")
    async def test_error_handling(
        self,
        mock_pg_cls,
        mock_chunk_fn,
        mock_connector,
        mock_parser,
        mock_embedder,
        mock_es_store,
        mock_db_session,
    ):
        """Errors should be caught, session rolled back, and error returned."""
        mock_connector.fetch_document = AsyncMock(side_effect=RuntimeError("fetch failed"))

        mock_pg = AsyncMock()
        mock_pg_cls.return_value = mock_pg

        pipeline = _make_pipeline(mock_connector, mock_parser, mock_embedder, mock_es_store, mock_db_session)
        result = await pipeline.ingest_document("/bad.md")

        assert result.error == "fetch failed"
        assert result.segments_created == 0
        mock_db_session.rollback.assert_called_once()

    @patch("pam.ingestion.pipeline.chunk_document")
    @patch("pam.ingestion.pipeline.PostgresStore")
    async def test_pg_commits_before_es_writes(
        self,
        mock_pg_cls,
        mock_chunk_fn,
        mock_connector,
        mock_parser,
        mock_embedder,
        mock_es_store,
        mock_db_session,
    ):
        """PG commit must happen before ES writes to prevent inconsistency."""
        raw_doc = RawDocument(
            content=b"# Test",
            content_type="text/markdown",
            source_id="/test.md",
            title="Test",
        )
        mock_connector.fetch_document = AsyncMock(return_value=raw_doc)
        mock_connector.get_content_hash = AsyncMock(return_value="newhash")

        mock_pg = AsyncMock()
        mock_pg.get_document_by_source = AsyncMock(return_value=None)
        doc_id = uuid.uuid4()
        mock_pg.upsert_document = AsyncMock(return_value=doc_id)
        mock_pg.save_segments = AsyncMock(return_value=1)
        mock_pg.log_sync = AsyncMock()
        mock_pg_cls.return_value = mock_pg

        mock_chunk = Mock(content="chunk", content_hash="h1", section_path=None, segment_type="text", position=0)
        mock_chunk_fn.return_value = [mock_chunk]
        mock_embedder.embed_texts_with_cache = AsyncMock(return_value=[[0.1] * 1536])

        # Track call order
        call_order = []
        mock_db_session.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))
        mock_es_store.delete_by_document = AsyncMock(side_effect=lambda *a: call_order.append("es_delete"))
        mock_es_store.bulk_index = AsyncMock(side_effect=lambda *a: call_order.append("es_index"))

        pipeline = _make_pipeline(mock_connector, mock_parser, mock_embedder, mock_es_store, mock_db_session)
        result = await pipeline.ingest_document("/test.md")

        assert result.error is None
        assert call_order.index("commit") < call_order.index("es_delete")
        assert call_order.index("commit") < call_order.index("es_index")

    @patch("pam.ingestion.pipeline.chunk_document")
    @patch("pam.ingestion.pipeline.PostgresStore")
    async def test_es_failure_after_pg_commit_does_not_crash(
        self,
        mock_pg_cls,
        mock_chunk_fn,
        mock_connector,
        mock_parser,
        mock_embedder,
        mock_es_store,
        mock_db_session,
    ):
        """ES write failure after PG commit should log but not raise."""
        raw_doc = RawDocument(
            content=b"# Test",
            content_type="text/markdown",
            source_id="/test.md",
            title="Test",
        )
        mock_connector.fetch_document = AsyncMock(return_value=raw_doc)
        mock_connector.get_content_hash = AsyncMock(return_value="newhash")

        mock_pg = AsyncMock()
        mock_pg.get_document_by_source = AsyncMock(return_value=None)
        doc_id = uuid.uuid4()
        mock_pg.upsert_document = AsyncMock(return_value=doc_id)
        mock_pg.save_segments = AsyncMock(return_value=1)
        mock_pg.log_sync = AsyncMock()
        mock_pg_cls.return_value = mock_pg

        mock_chunk = Mock(content="chunk", content_hash="h1", section_path=None, segment_type="text", position=0)
        mock_chunk_fn.return_value = [mock_chunk]
        mock_embedder.embed_texts_with_cache = AsyncMock(return_value=[[0.1] * 1536])

        # ES fails after PG commit
        mock_es_store.delete_by_document = AsyncMock(side_effect=RuntimeError("ES connection refused"))

        pipeline = _make_pipeline(mock_connector, mock_parser, mock_embedder, mock_es_store, mock_db_session)
        result = await pipeline.ingest_document("/test.md")

        # Should succeed — PG is authoritative, ES failure is tolerated
        assert result.error is None
        assert result.segments_created == 1
        mock_db_session.commit.assert_called_once()


class TestIngestAll:
    @patch("pam.ingestion.pipeline.chunk_document")
    @patch("pam.ingestion.pipeline.PostgresStore")
    async def test_ingests_all_documents(
        self,
        mock_pg_cls,
        mock_chunk_fn,
        mock_connector,
        mock_parser,
        mock_embedder,
        mock_es_store,
        mock_db_session,
    ):
        """ingest_all should iterate over all documents from the connector."""
        mock_connector.list_documents = AsyncMock(
            return_value=[
                DocumentInfo(source_id="/a.md", title="A"),
                DocumentInfo(source_id="/b.md", title="B"),
            ]
        )
        # Make each ingest_document call fail gracefully to keep things simple
        mock_connector.fetch_document = AsyncMock(side_effect=RuntimeError("test"))

        mock_pg = AsyncMock()
        mock_pg_cls.return_value = mock_pg

        pipeline = _make_pipeline(mock_connector, mock_parser, mock_embedder, mock_es_store, mock_db_session)
        results = await pipeline.ingest_all()

        assert len(results) == 2
        assert all(r.error for r in results)
