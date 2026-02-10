"""Tests for retrieval types — SearchQuery and SearchResult validation."""

import uuid

import pytest
from pydantic import ValidationError

from pam.retrieval.types import SearchQuery, SearchResult


class TestSearchQuery:
    def test_defaults(self):
        q = SearchQuery(query="what is revenue?")
        assert q.top_k == 10
        assert q.source_type is None
        assert q.project is None
        assert q.date_from is None
        assert q.date_to is None

    def test_top_k_bounds(self):
        q = SearchQuery(query="test", top_k=1)
        assert q.top_k == 1

        q = SearchQuery(query="test", top_k=50)
        assert q.top_k == 50

    def test_top_k_too_low(self):
        with pytest.raises(ValidationError):
            SearchQuery(query="test", top_k=0)

    def test_top_k_too_high(self):
        with pytest.raises(ValidationError):
            SearchQuery(query="test", top_k=51)

    def test_with_filters(self):
        q = SearchQuery(
            query="revenue",
            source_type="markdown",
            project="finance",
        )
        assert q.source_type == "markdown"
        assert q.project == "finance"


class TestSearchResult:
    def test_create(self):
        r = SearchResult(
            segment_id=uuid.uuid4(),
            content="Revenue was $10M",
            score=0.95,
            source_url="file:///test.md",
            document_title="Report",
            section_path="Finance > Q1",
        )
        assert r.score == 0.95
        assert r.segment_type == "text"

    def test_minimal(self):
        r = SearchResult(
            segment_id=uuid.uuid4(),
            content="test",
            score=0.5,
        )
        assert r.source_url is None
        assert r.document_title is None
