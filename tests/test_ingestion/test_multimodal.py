"""Tests for multimodal document processing."""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from pam.common.llm.base import BaseLLMClient, LLMResponse
from pam.ingestion.chunkers.hybrid_chunker import ChunkResult
from pam.ingestion.processors.multimodal import MultimodalConfig, MultimodalProcessor


@pytest.fixture
def mock_llm_client():
    """Mock LLM client with vision support."""
    client = AsyncMock(spec=BaseLLMClient)
    client.supports_vision = True
    client.model_name = "test-model"
    return client


@pytest.fixture
def sample_text_chunks():
    """Sample text chunks for context."""
    return [
        ChunkResult(
            content="Revenue grew 15% in Q1 2025.",
            content_hash="hash1",
            section_path="Financial Results",
            segment_type="text",
            position=0,
        ),
        ChunkResult(
            content="Operating margins improved to 22%.",
            content_hash="hash2",
            section_path="Financial Results > Margins",
            segment_type="text",
            position=1,
        ),
    ]


def _make_docling_doc_with_pictures():
    """Create a mock DoclingDocument with pictures."""
    from PIL import Image

    # Create a small test image
    img = Image.new("RGB", (10, 10), color="red")

    picture = MagicMock()
    picture.get_image.return_value = img

    doc = MagicMock()
    doc.pictures = [picture]
    doc.tables = []
    return doc


def _make_docling_doc_with_tables():
    """Create a mock DoclingDocument with tables."""
    table = MagicMock()
    table.export_to_markdown.return_value = "| Metric | Value |\n|--------|-------|\n| DAU | 50k |"

    doc = MagicMock()
    doc.pictures = []
    doc.tables = [table]
    return doc


class TestMultimodalProcessor:
    async def test_process_images_calls_vision_api(self, mock_llm_client, sample_text_chunks):
        """Test that image processing calls the VLM API."""
        mock_llm_client.complete_with_vision = AsyncMock(
            return_value=LLMResponse(
                text=json.dumps({
                    "description": "A bar chart showing revenue growth",
                    "key_elements": ["bars", "revenue axis", "quarters"],
                    "relevance": "Shows the 15% revenue growth mentioned in text",
                }),
                input_tokens=100,
                output_tokens=50,
            )
        )

        processor = MultimodalProcessor(llm_client=mock_llm_client)
        doc = _make_docling_doc_with_pictures()

        results = await processor.process_document(doc, sample_text_chunks)

        assert len(results) == 1
        assert results[0].segment_type == "image"
        assert "bar chart" in results[0].content
        assert "revenue growth" in results[0].content
        mock_llm_client.complete_with_vision.assert_called_once()

    async def test_process_tables_calls_llm_api(self, mock_llm_client, sample_text_chunks):
        """Test that table processing calls the LLM API."""
        mock_llm_client.complete = AsyncMock(
            return_value=LLMResponse(
                text=json.dumps({
                    "summary": "Daily active users metric at 50k",
                    "key_findings": ["DAU is 50k"],
                    "column_descriptions": {"Metric": "metric name", "Value": "metric value"},
                }),
                input_tokens=100,
                output_tokens=50,
            )
        )

        processor = MultimodalProcessor(llm_client=mock_llm_client)
        doc = _make_docling_doc_with_tables()

        results = await processor.process_document(doc, sample_text_chunks)

        assert len(results) == 1
        assert results[0].segment_type == "table"
        assert "DAU" in results[0].content
        mock_llm_client.complete.assert_called_once()

    async def test_robust_json_parse_direct(self, mock_llm_client):
        """Test direct JSON parsing."""
        processor = MultimodalProcessor(llm_client=mock_llm_client)
        result = processor._robust_json_parse('{"key": "value"}')
        assert result == {"key": "value"}

    async def test_robust_json_parse_markdown_fences(self, mock_llm_client):
        """Test JSON parsing with markdown code fences."""
        processor = MultimodalProcessor(llm_client=mock_llm_client)
        result = processor._robust_json_parse('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    async def test_robust_json_parse_embedded(self, mock_llm_client):
        """Test JSON parsing with surrounding text."""
        processor = MultimodalProcessor(llm_client=mock_llm_client)
        result = processor._robust_json_parse('Here is the analysis:\n{"key": "value"}\nDone.')
        assert result == {"key": "value"}

    async def test_robust_json_parse_invalid(self, mock_llm_client):
        """Test JSON parsing with invalid input."""
        processor = MultimodalProcessor(llm_client=mock_llm_client)
        result = processor._robust_json_parse("This is not JSON at all")
        assert result is None

    async def test_context_extraction(self, mock_llm_client, sample_text_chunks):
        """Test that context is extracted from nearby chunks."""
        processor = MultimodalProcessor(
            llm_client=mock_llm_client,
            config=MultimodalConfig(context_window_chars=500),
        )
        context = processor._extract_context(sample_text_chunks, 0)
        assert "Revenue" in context
        assert len(context) <= 500

    async def test_context_extraction_empty(self, mock_llm_client):
        """Test context extraction with no chunks."""
        processor = MultimodalProcessor(llm_client=mock_llm_client)
        context = processor._extract_context([], 0)
        assert "No surrounding text" in context

    async def test_multimodal_disabled_by_default(self, mock_llm_client, sample_text_chunks):
        """Test that disabling image and table processing skips them."""
        config = MultimodalConfig(
            enable_image_processing=False,
            enable_table_processing=False,
        )
        processor = MultimodalProcessor(llm_client=mock_llm_client, config=config)

        doc = MagicMock()
        doc.pictures = [MagicMock()]
        doc.tables = [MagicMock()]

        results = await processor.process_document(doc, sample_text_chunks)
        assert len(results) == 0

    async def test_graceful_failure(self, mock_llm_client, sample_text_chunks):
        """Test that VLM errors don't crash the pipeline."""
        mock_llm_client.complete_with_vision = AsyncMock(
            side_effect=Exception("VLM service unavailable")
        )

        processor = MultimodalProcessor(llm_client=mock_llm_client)
        doc = _make_docling_doc_with_pictures()

        # Should not raise, just return empty results
        results = await processor.process_document(doc, sample_text_chunks)
        assert len(results) == 0

    async def test_no_vision_support_skips_images(self, sample_text_chunks):
        """Test that images are skipped if LLM client doesn't support vision."""
        client = AsyncMock(spec=BaseLLMClient)
        client.supports_vision = False

        processor = MultimodalProcessor(llm_client=client)
        doc = _make_docling_doc_with_pictures()

        results = await processor.process_document(doc, sample_text_chunks)
        assert len(results) == 0

    async def test_pipeline_with_multimodal(self, mock_llm_client, sample_text_chunks):
        """Test that multimodal chunks are integrated into pipeline flow."""
        mock_llm_client.complete = AsyncMock(
            return_value=LLMResponse(
                text=json.dumps({
                    "summary": "Metrics table",
                    "key_findings": ["DAU at 50k"],
                    "column_descriptions": {},
                }),
            )
        )

        processor = MultimodalProcessor(llm_client=mock_llm_client)
        doc = _make_docling_doc_with_tables()

        results = await processor.process_document(doc, sample_text_chunks)

        # Verify position offset is applied
        assert results[0].position == len(sample_text_chunks)

        # Verify content hash is set
        assert results[0].content_hash is not None
        assert len(results[0].content_hash) == 64  # SHA-256 hex
