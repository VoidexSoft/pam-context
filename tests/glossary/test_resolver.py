"""Tests for AliasResolver query expansion."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pam.glossary.resolver import AliasResolver


@pytest.fixture
def mock_glossary_store() -> AsyncMock:
    """Mock GlossaryStore for resolver tests."""
    store = AsyncMock()
    store.search_by_alias = AsyncMock(return_value=[])
    return store


@pytest.fixture
def resolver(mock_glossary_store) -> AliasResolver:
    return AliasResolver(store=mock_glossary_store)


@pytest.mark.asyncio
async def test_resolve_expands_known_alias(resolver, mock_glossary_store):
    """resolve() expands known aliases to canonical terms."""
    mock_glossary_store.search_by_alias.return_value = [
        {
            "term_id": "abc",
            "score": 10.0,
            "canonical": "Gross Bookings",
            "aliases": ["GBs", "gross books"],
            "definition": "Total fare amount",
            "category": "metric",
        }
    ]

    result = await resolver.resolve("What's the GBs target?")

    assert "Gross Bookings" in result.expanded_query
    assert len(result.resolved_terms) == 1
    assert result.resolved_terms[0].canonical == "Gross Bookings"
    assert result.original_query == "What's the GBs target?"


@pytest.mark.asyncio
async def test_resolve_no_matches_returns_original(resolver, mock_glossary_store):
    """resolve() returns original query when no aliases match."""
    mock_glossary_store.search_by_alias.return_value = []

    result = await resolver.resolve("What is the revenue?")

    assert result.expanded_query == "What is the revenue?"
    assert result.resolved_terms == []


@pytest.mark.asyncio
async def test_resolve_skips_low_score(resolver, mock_glossary_store):
    """resolve() skips matches below min_score threshold."""
    mock_glossary_store.search_by_alias.return_value = [
        {
            "term_id": "abc",
            "score": 1.0,  # Below default min_score of 3.0
            "canonical": "Gross Bookings",
            "aliases": ["GBs"],
            "definition": "Total fare",
            "category": "metric",
        }
    ]

    result = await resolver.resolve("What's the GBs target?")

    assert result.expanded_query == "What's the GBs target?"
    assert result.resolved_terms == []


@pytest.mark.asyncio
async def test_resolve_deduplicates_canonicals(resolver, mock_glossary_store):
    """resolve() doesn't add the same canonical term twice."""
    mock_glossary_store.search_by_alias.side_effect = [
        [{"term_id": "abc", "score": 10.0, "canonical": "Gross Bookings",
          "aliases": ["GBs"], "definition": "Total fare", "category": "metric"}],
        [{"term_id": "abc", "score": 10.0, "canonical": "Gross Bookings",
          "aliases": ["GBs"], "definition": "Total fare", "category": "metric"}],
        [],
        [],
        [],
    ]

    result = await resolver.resolve("GBs and GBs trend")

    canonical_matches = [rt.canonical for rt in result.resolved_terms]
    assert canonical_matches.count("Gross Bookings") <= 1


def test_extract_candidates_abbreviations(resolver):
    """_extract_candidates picks up uppercase abbreviations."""
    candidates = resolver._extract_candidates("What's the GBs in EMEA?")
    candidate_lower = [c.lower() for c in candidates]
    assert "gbs" in candidate_lower
    assert "emea" in candidate_lower


def test_extract_candidates_quoted(resolver):
    """_extract_candidates picks up quoted terms."""
    candidates = resolver._extract_candidates('Look up "Gross Bookings" please')
    assert "Gross Bookings" in candidates


def test_extract_candidates_filters_stop_words(resolver):
    """_extract_candidates filters out stop words."""
    candidates = resolver._extract_candidates("what is the target")
    candidate_lower = [c.lower() for c in candidates]
    assert "what" not in candidate_lower
    assert "the" not in candidate_lower
    assert "target" in candidate_lower
