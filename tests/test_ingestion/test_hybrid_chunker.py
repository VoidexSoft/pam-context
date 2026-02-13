"""Tests for hybrid_chunker — chunk_document and _extract_section_path."""

import hashlib
from unittest.mock import Mock, patch

from pam.ingestion.chunkers.hybrid_chunker import (
    _extract_section_path,
    chunk_document,
)

PATCH_TARGET = "docling.chunking.HybridChunker"


class TestChunkDocument:
    @patch(PATCH_TARGET)
    def test_basic_chunking(self, mock_chunker_cls):
        """Should produce ChunkResult objects from Docling chunks."""
        mock_chunk = Mock()
        mock_chunk.text = "This is chunk content."
        mock_chunk.meta = None
        mock_chunker_cls.model_validate.return_value.chunk.return_value = [mock_chunk]

        doc = Mock()
        results = chunk_document(doc, max_tokens=256)

        assert len(results) == 1
        assert results[0].content == "This is chunk content."
        assert results[0].position == 0
        assert results[0].segment_type == "text"
        assert results[0].content_hash == hashlib.sha256(b"This is chunk content.").hexdigest()

    @patch(PATCH_TARGET)
    def test_empty_chunks_skipped(self, mock_chunker_cls):
        """Empty or whitespace-only chunks should be filtered out."""
        mock_chunks = [
            Mock(text="Valid content", meta=None),
            Mock(text="   ", meta=None),
            Mock(text="", meta=None),
            Mock(text="Also valid", meta=None),
        ]
        mock_chunker_cls.model_validate.return_value.chunk.return_value = mock_chunks

        results = chunk_document(Mock())
        assert len(results) == 2
        assert results[0].content == "Valid content"
        assert results[1].content == "Also valid"

    @patch(PATCH_TARGET)
    def test_positions_are_sequential(self, mock_chunker_cls):
        """Positions should reflect original index, not filtered index."""
        chunks = [Mock(text=f"Chunk {i}", meta=None) for i in range(3)]
        mock_chunker_cls.model_validate.return_value.chunk.return_value = chunks

        results = chunk_document(Mock())
        assert [r.position for r in results] == [0, 1, 2]

    @patch(PATCH_TARGET)
    def test_table_segment_type(self, mock_chunker_cls):
        """Chunks with table items should have segment_type='table'."""
        item = Mock()
        item.label = "TableItem"
        meta = Mock()
        meta.doc_items = [item]
        meta.headings = None
        chunk = Mock(text="Table data", meta=meta)
        mock_chunker_cls.model_validate.return_value.chunk.return_value = [chunk]

        results = chunk_document(Mock())
        assert results[0].segment_type == "table"

    @patch(PATCH_TARGET)
    def test_uses_settings_default_tokens(self, mock_chunker_cls):
        """When max_tokens is None, should use settings.chunk_size_tokens."""
        mock_chunker_cls.model_validate.return_value.chunk.return_value = []
        chunk_document(Mock(), max_tokens=None)
        # Verify HybridChunker.model_validate was called with default from settings
        call_args = mock_chunker_cls.model_validate.call_args[0][0]
        assert "max_tokens" in call_args


class TestExtractSectionPath:
    def test_with_headings(self):
        chunk = Mock()
        chunk.meta = Mock()
        chunk.meta.headings = ["Introduction", "Overview"]
        assert _extract_section_path(chunk) == "Introduction > Overview"

    def test_no_meta(self):
        chunk = Mock(spec=[])  # no meta attribute
        assert _extract_section_path(chunk) is None

    def test_meta_no_headings(self):
        chunk = Mock()
        chunk.meta = Mock()
        chunk.meta.headings = None
        assert _extract_section_path(chunk) is None

    def test_empty_headings(self):
        chunk = Mock()
        chunk.meta = Mock()
        chunk.meta.headings = []
        assert _extract_section_path(chunk) is None
