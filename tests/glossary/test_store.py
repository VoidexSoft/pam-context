"""Tests for GlossaryStore ES operations."""

from __future__ import annotations

import uuid

import pytest

from pam.glossary.store import get_glossary_index_mapping


def test_glossary_index_mapping_structure():
    """Index mapping has correct fields and types."""
    mapping = get_glossary_index_mapping(1536)
    props = mapping["mappings"]["properties"]

    assert props["embedding"]["type"] == "dense_vector"
    assert props["embedding"]["dims"] == 1536
    assert props["embedding"]["similarity"] == "cosine"
    assert props["canonical"]["type"] == "keyword"
    assert props["aliases"]["type"] == "keyword"
    assert props["definition"]["type"] == "text"
    assert props["category"]["type"] == "keyword"
    assert props["project_id"]["type"] == "keyword"


@pytest.mark.asyncio
async def test_ensure_index_creates_when_missing(glossary_store, mock_es_client):
    """ensure_index creates the index when it doesn't exist."""
    mock_es_client.indices.exists.return_value = False

    await glossary_store.ensure_index()

    mock_es_client.indices.create.assert_awaited_once()
    call_kwargs = mock_es_client.indices.create.call_args
    assert call_kwargs.kwargs["index"] == "test_glossary"


@pytest.mark.asyncio
async def test_ensure_index_skips_when_exists(glossary_store, mock_es_client):
    """ensure_index is a no-op when index already exists."""
    mock_es_client.indices.exists.return_value = True

    await glossary_store.ensure_index()

    mock_es_client.indices.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_term(glossary_store, mock_es_client):
    """index_term indexes a glossary term in ES."""
    term_id = uuid.uuid4()
    embedding = [0.1] * 1536

    await glossary_store.index_term(
        term_id=term_id,
        canonical="Gross Bookings",
        aliases=["GBs", "gross books"],
        definition="Total fare amount before deductions",
        embedding=embedding,
        category="metric",
        project_id=uuid.uuid4(),
    )

    mock_es_client.index.assert_awaited_once()
    call_kwargs = mock_es_client.index.call_args.kwargs
    assert call_kwargs["index"] == "test_glossary"
    assert call_kwargs["id"] == str(term_id)
    assert call_kwargs["document"]["canonical"] == "Gross Bookings"
    assert call_kwargs["document"]["aliases"] == ["GBs", "gross books"]


@pytest.mark.asyncio
async def test_search_terms(glossary_store, mock_es_client):
    """search returns scored term IDs from kNN search."""
    term_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(term_id),
                    "_score": 0.95,
                    "_source": {
                        "canonical": "Gross Bookings",
                        "aliases": ["GBs"],
                        "definition": "Total fare amount",
                        "category": "metric",
                    },
                }
            ]
        }
    }

    results = await glossary_store.search(
        query_embedding=[0.1] * 1536,
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["canonical"] == "Gross Bookings"
    assert results[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_search_by_alias(glossary_store, mock_es_client):
    """search_by_alias finds terms by keyword match on canonical/aliases."""
    term_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(term_id),
                    "_score": 8.5,
                    "_source": {
                        "canonical": "Gross Bookings",
                        "aliases": ["GBs", "gross books"],
                        "definition": "Total fare amount",
                        "category": "metric",
                    },
                }
            ]
        }
    }

    results = await glossary_store.search_by_alias(alias="GBs")

    assert len(results) == 1
    assert results[0]["canonical"] == "Gross Bookings"
    mock_es_client.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_term(glossary_store, mock_es_client):
    """delete removes a term from ES."""
    term_id = uuid.uuid4()
    options_mock = mock_es_client.options.return_value

    await glossary_store.delete(term_id)

    mock_es_client.options.assert_called_once_with(ignore_status=404)
    options_mock.delete.assert_awaited_once()
