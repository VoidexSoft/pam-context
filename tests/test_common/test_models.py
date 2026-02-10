"""Tests for pam.common.models — Pydantic schema validation."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pam.common.models import (
    DocumentInfo,
    DocumentResponse,
    KnowledgeSegment,
    RawDocument,
)


class TestKnowledgeSegment:
    def test_create_with_defaults(self):
        seg = KnowledgeSegment(
            content="test content",
            content_hash="abc123",
            source_type="markdown",
            source_id="/test.md",
        )
        assert seg.content == "test content"
        assert seg.embedding is None
        assert seg.segment_type == "text"
        assert seg.position == 0
        assert seg.metadata == {}
        assert isinstance(seg.id, uuid.UUID)

    def test_create_with_all_fields(self):
        doc_id = uuid.uuid4()
        seg = KnowledgeSegment(
            content="test",
            content_hash="hash",
            embedding=[0.1, 0.2],
            source_type="google_doc",
            source_id="abc",
            source_url="https://example.com",
            section_path="Intro > Overview",
            segment_type="table",
            position=5,
            metadata={"key": "value"},
            document_title="My Doc",
            document_id=doc_id,
        )
        assert seg.embedding == [0.1, 0.2]
        assert seg.source_type == "google_doc"
        assert seg.segment_type == "table"
        assert seg.document_id == doc_id

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            KnowledgeSegment(content="test")  # missing content_hash, source_type, source_id


class TestDocumentResponse:
    def test_valid_response(self):
        now = datetime.now(UTC)
        resp = DocumentResponse(
            id=uuid.uuid4(),
            source_type="markdown",
            source_id="/test.md",
            source_url=None,
            title="Test",
            owner=None,
            status="active",
            content_hash="abc",
            last_synced_at=now,
            created_at=now,
            segment_count=5,
        )
        assert resp.segment_count == 5
        assert resp.status == "active"

    def test_default_segment_count(self):
        now = datetime.now(UTC)
        resp = DocumentResponse(
            id=uuid.uuid4(),
            source_type="markdown",
            source_id="/test.md",
            source_url=None,
            title="Test",
            owner=None,
            status="active",
            content_hash=None,
            last_synced_at=None,
            created_at=now,
        )
        assert resp.segment_count == 0


class TestDocumentInfo:
    def test_minimal(self):
        info = DocumentInfo(source_id="abc", title="My Doc")
        assert info.owner is None
        assert info.source_url is None
        assert info.modified_at is None

    def test_full(self):
        now = datetime.now(UTC)
        info = DocumentInfo(
            source_id="abc",
            title="My Doc",
            owner="user@example.com",
            source_url="https://example.com",
            modified_at=now,
        )
        assert info.owner == "user@example.com"


class TestRawDocument:
    def test_create(self):
        doc = RawDocument(
            content=b"hello",
            content_type="text/markdown",
            source_id="test.md",
            title="Test",
        )
        assert doc.content == b"hello"
        assert doc.metadata == {}
        assert doc.source_url is None

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            RawDocument(content=b"hello")  # missing content_type, source_id, title
