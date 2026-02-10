"""Tests for DoclingParser — document parsing via Docling."""

from unittest.mock import Mock, patch

import pytest

from pam.common.models import RawDocument
from pam.ingestion.parsers.docling_parser import DoclingParser


class TestDoclingParser:
    @patch("pam.ingestion.parsers.docling_parser.DocumentConverter")
    def test_parse_markdown(self, mock_converter_cls):
        mock_doc = Mock()
        mock_result = Mock()
        mock_result.document = mock_doc
        mock_converter_cls.return_value.convert.return_value = mock_result

        parser = DoclingParser()
        raw = RawDocument(
            content=b"# Test\n\nHello world",
            content_type="text/markdown",
            source_id="test.md",
            title="Test",
        )
        result = parser.parse(raw)
        assert result is mock_doc
        mock_converter_cls.return_value.convert.assert_called_once()

    @patch("pam.ingestion.parsers.docling_parser.DocumentConverter")
    def test_parse_docx(self, mock_converter_cls):
        mock_result = Mock()
        mock_result.document = Mock()
        mock_converter_cls.return_value.convert.return_value = mock_result

        parser = DoclingParser()
        raw = RawDocument(
            content=b"fake docx content",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            source_id="test.docx",
            title="Test",
        )
        result = parser.parse(raw)
        assert result is mock_result.document

    @patch("pam.ingestion.parsers.docling_parser.DocumentConverter")
    def test_parse_error_propagates(self, mock_converter_cls):
        mock_converter_cls.return_value.convert.side_effect = RuntimeError("Parse failed")

        parser = DoclingParser()
        raw = RawDocument(
            content=b"bad content",
            content_type="text/markdown",
            source_id="bad.md",
            title="Bad",
        )
        with pytest.raises(RuntimeError, match="Parse failed"):
            parser.parse(raw)

    @patch("pam.ingestion.parsers.docling_parser.DocumentConverter")
    def test_temp_file_cleaned_up_on_success(self, mock_converter_cls):
        """Temp file should be deleted after successful parse."""
        import os
        temp_paths = []

        def capture_path(path):
            temp_paths.append(path)
            mock_result = Mock()
            mock_result.document = Mock()
            return mock_result

        mock_converter_cls.return_value.convert.side_effect = capture_path

        parser = DoclingParser()
        raw = RawDocument(
            content=b"# Test",
            content_type="text/markdown",
            source_id="test.md",
            title="Test",
        )
        parser.parse(raw)
        assert len(temp_paths) == 1
        assert not os.path.exists(temp_paths[0])

    @patch("pam.ingestion.parsers.docling_parser.DocumentConverter")
    def test_temp_file_cleaned_up_on_error(self, mock_converter_cls):
        """Temp file should be deleted even if parsing fails."""
        import os
        temp_paths = []

        def capture_and_fail(path):
            temp_paths.append(path)
            raise RuntimeError("fail")

        mock_converter_cls.return_value.convert.side_effect = capture_and_fail

        parser = DoclingParser()
        raw = RawDocument(
            content=b"# Test",
            content_type="text/markdown",
            source_id="test.md",
            title="Test",
        )
        with pytest.raises(RuntimeError):
            parser.parse(raw)
        assert len(temp_paths) == 1
        assert not os.path.exists(temp_paths[0])
