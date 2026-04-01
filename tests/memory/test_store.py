"""Tests for MemoryStore ES operations."""

from __future__ import annotations

import uuid

import pytest

from pam.memory.store import MemoryStore, get_memory_index_mapping


def test_memory_index_mapping_structure():
    """Index mapping has correct fields and types."""
    mapping = get_memory_index_mapping(1536)
    props = mapping["mappings"]["properties"]

    assert props["embedding"]["type"] == "dense_vector"
    assert props["embedding"]["dims"] == 1536
    assert props["embedding"]["similarity"] == "cosine"
    assert props["user_id"]["type"] == "keyword"
    assert props["project_id"]["type"] == "keyword"
    assert props["type"]["type"] == "keyword"
    assert props["content"]["type"] == "text"
    assert props["importance"]["type"] == "float"


@pytest.mark.asyncio
async def test_ensure_index_creates_when_missing(memory_store, mock_es_client):
    """ensure_index creates the index when it doesn't exist."""
    mock_es_client.indices.exists.return_value = False

    await memory_store.ensure_index()

    mock_es_client.indices.create.assert_awaited_once()
    call_kwargs = mock_es_client.indices.create.call_args
    assert call_kwargs.kwargs["index"] == "test_memories"


@pytest.mark.asyncio
async def test_ensure_index_skips_when_exists(memory_store, mock_es_client):
    """ensure_index is a no-op when index already exists."""
    mock_es_client.indices.exists.return_value = True

    await memory_store.ensure_index()

    mock_es_client.indices.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_memory(memory_store, mock_es_client):
    """index_memory indexes a memory document in ES."""
    memory_id = uuid.uuid4()
    embedding = [0.1] * 1536

    await memory_store.index_memory(
        memory_id=memory_id,
        content="User prefers Python",
        embedding=embedding,
        user_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        memory_type="preference",
        importance=0.7,
    )

    mock_es_client.index.assert_awaited_once()
    call_kwargs = mock_es_client.index.call_args.kwargs
    assert call_kwargs["index"] == "test_memories"
    assert call_kwargs["id"] == str(memory_id)
    assert call_kwargs["document"]["content"] == "User prefers Python"
    assert call_kwargs["document"]["importance"] == 0.7


@pytest.mark.asyncio
async def test_search_memories(memory_store, mock_es_client):
    """search returns scored memory IDs from kNN search."""
    memory_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(memory_id),
                    "_score": 0.95,
                    "_source": {
                        "content": "User prefers Python",
                        "user_id": str(uuid.uuid4()),
                        "type": "preference",
                        "importance": 0.7,
                    },
                }
            ],
            "total": {"value": 1},
        }
    }

    results = await memory_store.search(
        query_embedding=[0.1] * 1536,
        user_id=uuid.uuid4(),
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["memory_id"] == str(memory_id)
    assert results[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_find_duplicates(memory_store, mock_es_client):
    """find_duplicates returns high-similarity matches."""
    dup_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(dup_id),
                    "_score": 0.95,
                    "_source": {
                        "content": "User likes Python",
                        "user_id": str(uuid.uuid4()),
                        "type": "preference",
                    },
                }
            ]
        }
    }

    results = await memory_store.find_duplicates(
        embedding=[0.1] * 1536,
        user_id=uuid.uuid4(),
        threshold=0.9,
    )

    assert len(results) == 1
    assert results[0]["memory_id"] == str(dup_id)
    assert results[0]["score"] >= 0.9


@pytest.mark.asyncio
async def test_delete_memory(memory_store, mock_es_client):
    """delete removes a memory from the ES index."""
    memory_id = uuid.uuid4()

    await memory_store.delete(memory_id)

    mock_es_client.options.assert_called_once_with(ignore_status=404)
    mock_es_client.options.return_value.delete.assert_awaited_once_with(
        index="test_memories",
        id=str(memory_id),
        refresh="wait_for",
    )
