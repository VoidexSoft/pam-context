"""Tests for base parser and ParsedDocument."""

from unittest.mock import MagicMock, Mock

import pytest

from pam.ingestion.parsers.base import BaseParser, ParsedDocument, ParsedImage, ParsedTable


class TestParsedDocument:
    def test_minimal(self):
        doc = ParsedDocument(markdown_content="# Hello")
        assert doc.markdown_content == "# Hello"
        assert doc.images == []
        assert doc.tables == []
        assert doc._docling_doc is None

    def test_with_images(self):
        doc = ParsedDocument(
            markdown_content="# Hello",
            images=[ParsedImage(image_data=b"png data", position=0)],
        )
        assert len(doc.images) == 1
        assert doc.images[0].image_data == b"png data"

    def test_with_tables(self):
        doc = ParsedDocument(
            markdown_content="# Hello",
            tables=[ParsedTable(markdown="| A | B |", position=0)],
        )
        assert len(doc.tables) == 1

    def test_with_docling_doc(self):
        mock_doc = Mock()
        doc = ParsedDocument(
            markdown_content="# Hello",
            _docling_doc=mock_doc,
        )
        assert doc._docling_doc is mock_doc


class TestParsedImage:
    def test_defaults(self):
        img = ParsedImage()
        assert img.image_data is None
        assert img.caption is None
        assert img.page_number is None
        assert img.position == 0


class TestParsedTable:
    def test_with_caption(self):
        t = ParsedTable(markdown="| A |\n|---|\n| 1 |", caption="Table 1", page_number=3)
        assert t.caption == "Table 1"
        assert t.page_number == 3
