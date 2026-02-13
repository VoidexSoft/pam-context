"""Tests for PAM <-> Haystack type conversion adapters."""

from __future__ import annotations

import uuid

import pytest
from haystack import Document

from pam.common.haystack_adapter import haystack_doc_to_search_result, segment_to_haystack_doc
from pam.common.models import KnowledgeSegment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def segment_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def document_id() -> uuid.UUID:
    return uuid.UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def full_segment(segment_id: uuid.UUID, document_id: uuid.UUID) -> KnowledgeSegment:
    """A KnowledgeSegment with all fields populated."""
    return KnowledgeSegment(
        id=segment_id,
        content="Revenue grew 15% year-over-year.",
        content_hash="abc123",
        embedding=[0.1, 0.2, 0.3],
        source_type="markdown",
        source_id="/docs/report.md",
        source_url="file:///docs/report.md",
        section_path="Finance > Revenue",
        segment_type="text",
        position=3,
        metadata={"extra": "value"},
        document_title="Annual Report",
        document_id=document_id,
    )


@pytest.fixture
def minimal_segment(segment_id: uuid.UUID) -> KnowledgeSegment:
    """A KnowledgeSegment with only required fields."""
    return KnowledgeSegment(
        id=segment_id,
        content="Some content",
        content_hash="def456",
        source_type="confluence",
        source_id="page-123",
    )


# ---------------------------------------------------------------------------
# segment_to_haystack_doc
# ---------------------------------------------------------------------------


class TestSegmentToHaystackDoc:
    def test_maps_all_fields(self, full_segment: KnowledgeSegment, segment_id: uuid.UUID, document_id: uuid.UUID):
        doc = segment_to_haystack_doc(full_segment)

        assert isinstance(doc, Document)
        assert doc.id == str(segment_id)
        assert doc.content == "Revenue grew 15% year-over-year."
        assert doc.embedding == [0.1, 0.2, 0.3]

        meta = doc.meta
        assert meta["segment_id"] == str(segment_id)
        assert meta["document_id"] == str(document_id)
        assert meta["source_type"] == "markdown"
        assert meta["source_id"] == "/docs/report.md"
        assert meta["source_url"] == "file:///docs/report.md"
        assert meta["document_title"] == "Annual Report"
        assert meta["section_path"] == "Finance > Revenue"
        assert meta["segment_type"] == "text"
        assert meta["position"] == 3

    def test_handles_none_document_id(self, minimal_segment: KnowledgeSegment):
        doc = segment_to_haystack_doc(minimal_segment)

        assert doc.meta["document_id"] is None
        assert doc.meta["source_url"] is None
        assert doc.meta["document_title"] is None
        assert doc.meta["section_path"] is None

    def test_none_embedding_preserved(self, minimal_segment: KnowledgeSegment):
        assert minimal_segment.embedding is None
        doc = segment_to_haystack_doc(minimal_segment)
        assert doc.embedding is None

    def test_default_segment_type_and_position(self, minimal_segment: KnowledgeSegment):
        doc = segment_to_haystack_doc(minimal_segment)
        assert doc.meta["segment_type"] == "text"
        assert doc.meta["position"] == 0


# ---------------------------------------------------------------------------
# haystack_doc_to_search_result
# ---------------------------------------------------------------------------


class TestHaystackDocToSearchResult:
    def test_maps_all_fields_from_meta(self, segment_id: uuid.UUID):
        doc = Document(
            id=str(segment_id),
            content="Test content",
            score=0.85,
            meta={
                "segment_id": str(segment_id),
                "source_url": "file:///test.md",
                "source_id": "/test.md",
                "section_path": "Intro",
                "document_title": "Test Doc",
                "segment_type": "table",
            },
        )

        result = haystack_doc_to_search_result(doc)

        assert result.segment_id == segment_id
        assert result.content == "Test content"
        assert result.score == 0.85
        assert result.source_url == "file:///test.md"
        assert result.source_id == "/test.md"
        assert result.section_path == "Intro"
        assert result.document_title == "Test Doc"
        assert result.segment_type == "table"

    def test_explicit_score_overrides_doc_score(self, segment_id: uuid.UUID):
        doc = Document(
            id=str(segment_id),
            content="Content",
            score=0.5,
            meta={"segment_id": str(segment_id)},
        )

        result = haystack_doc_to_search_result(doc, score=0.99)
        assert result.score == 0.99

    def test_falls_back_to_doc_score(self, segment_id: uuid.UUID):
        doc = Document(
            id=str(segment_id),
            content="Content",
            score=0.72,
            meta={"segment_id": str(segment_id)},
        )

        result = haystack_doc_to_search_result(doc, score=None)
        assert result.score == 0.72

    def test_falls_back_to_zero_when_no_scores(self, segment_id: uuid.UUID):
        doc = Document(
            id=str(segment_id),
            content="Content",
            meta={"segment_id": str(segment_id)},
        )
        # Haystack Document.score defaults to None
        assert doc.score is None

        result = haystack_doc_to_search_result(doc)
        assert result.score == 0.0

    def test_uses_doc_id_when_segment_id_missing_from_meta(self):
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, content="Content", meta={})

        result = haystack_doc_to_search_result(doc)
        assert result.segment_id == uuid.UUID(doc_id)

    def test_handles_none_meta(self):
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, content="Content")
        doc.meta = None  # type: ignore[assignment]

        result = haystack_doc_to_search_result(doc)
        assert result.segment_id == uuid.UUID(doc_id)
        assert result.source_url is None
        assert result.source_id is None
        assert result.section_path is None
        assert result.document_title is None
        assert result.segment_type == "text"

    def test_missing_optional_meta_fields(self, segment_id: uuid.UUID):
        doc = Document(
            id=str(segment_id),
            content="Content",
            score=0.5,
            meta={"segment_id": str(segment_id)},
        )

        result = haystack_doc_to_search_result(doc)
        assert result.source_url is None
        assert result.source_id is None
        assert result.section_path is None
        assert result.document_title is None
        assert result.segment_type == "text"

    def test_empty_content_becomes_empty_string(self, segment_id: uuid.UUID):
        doc = Document(
            id=str(segment_id),
            content=None,
            meta={"segment_id": str(segment_id)},
        )

        result = haystack_doc_to_search_result(doc)
        assert result.content == ""


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_segment_to_doc_to_result_preserves_data(
        self, full_segment: KnowledgeSegment, segment_id: uuid.UUID
    ):
        """segment -> haystack doc -> search result should preserve key fields."""
        doc = segment_to_haystack_doc(full_segment)
        doc.score = 0.92  # Simulate a score assigned by retrieval

        result = haystack_doc_to_search_result(doc)

        assert result.segment_id == segment_id
        assert result.content == full_segment.content
        assert result.score == 0.92
        assert result.source_url == full_segment.source_url
        assert result.source_id == full_segment.source_id
        assert result.section_path == full_segment.section_path
        assert result.document_title == full_segment.document_title
        assert result.segment_type == full_segment.segment_type

    def test_round_trip_with_minimal_segment(
        self, minimal_segment: KnowledgeSegment, segment_id: uuid.UUID
    ):
        doc = segment_to_haystack_doc(minimal_segment)
        doc.score = 0.5

        result = haystack_doc_to_search_result(doc)

        assert result.segment_id == segment_id
        assert result.content == minimal_segment.content
        assert result.score == 0.5
        assert result.source_url is None
        assert result.segment_type == "text"
