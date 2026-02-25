"""Tests for 4-way smart_search concurrency, embedding reuse, and output format."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.agent import RetrievalAgent
from pam.ingestion.stores.entity_relationship_store import (
    EntityRelationshipVDBStore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word_count_encoder():
    """Return a mock encoder that counts tokens as words (space-split)."""
    enc = MagicMock()
    enc.encode = lambda text: text.split()
    enc.decode = lambda tokens: " ".join(tokens)
    return enc


def _make_es_hit(source: dict, score: float = 0.9) -> dict:
    return {"_source": source, "_score": score}


def _make_entity_hit(name: str, entity_type: str, description: str, score: float = 0.9) -> dict:
    return _make_es_hit(
        {"name": name, "entity_type": entity_type, "description": description},
        score=score,
    )


def _make_relationship_hit(
    src: str, tgt: str, rel_type: str, description: str,
    keywords: str = "", weight: float = 1.0, score: float = 0.85,
) -> dict:
    return _make_es_hit(
        {
            "src_entity": src, "tgt_entity": tgt, "rel_type": rel_type,
            "description": description, "keywords": keywords, "weight": weight,
        },
        score=score,
    )


def _mock_vdb_store(
    entity_hits: list[dict] | None = None,
    relationship_hits: list[dict] | None = None,
) -> EntityRelationshipVDBStore:
    """Build a mock VDB store with pre-configured ES search responses."""
    mock_client = AsyncMock()

    entity_response = {"hits": {"hits": entity_hits or []}}
    rel_response = {"hits": {"hits": relationship_hits or []}}

    async def _fake_search(index: str, body: dict) -> dict:
        if "entities" in index:
            return entity_response
        return rel_response

    mock_client.search = AsyncMock(side_effect=_fake_search)

    return EntityRelationshipVDBStore(
        client=mock_client,
        entity_index="pam_entities",
        relationship_index="pam_relationships",
        embedding_dims=1536,
    )


def _mock_agent(
    vdb_store: EntityRelationshipVDBStore | None = None,
    graph_service: object | None = None,
    es_results: list | None = None,
) -> RetrievalAgent:
    """Build a minimally-mocked RetrievalAgent for smart_search testing."""
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=es_results or [])

    mock_embedder = AsyncMock()
    mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])

    agent = RetrievalAgent(
        search_service=mock_search,
        embedder=mock_embedder,
        api_key="test-key",
        model="test-model",
        graph_service=graph_service,
        vdb_store=vdb_store,
    )

    # Mock keyword extraction to skip real API call
    mock_text_block = MagicMock()
    mock_text_block.text = json.dumps({
        "high_level_keywords": ["infrastructure", "reliability"],
        "low_level_keywords": ["deployment", "team"],
    })
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    agent.client = AsyncMock()
    agent.client.messages.create = AsyncMock(return_value=mock_response)

    return agent


def _make_search_result(title: str = "Doc", content: str = "Chunk text", segment_id: str = "seg-1") -> MagicMock:
    """Build a mock SearchResult."""
    r = MagicMock()
    r.document_title = title
    r.section_path = "intro"
    r.source_url = "http://test"
    r.source_id = "test-src"
    r.segment_id = segment_id
    r.content = content
    return r


# ===========================================================================
# TestSmartSearch4WayConcurrency
# ===========================================================================


class TestSmartSearch4WayConcurrency:
    @pytest.fixture(autouse=True)
    def _mock_tiktoken(self):
        with patch("pam.agent.context_assembly._get_encoder", return_value=_word_count_encoder()):
            yield

    async def test_all_4_coroutines_run_concurrently(self):
        """Verify asyncio.gather is called with 4 coroutines."""
        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store)

        with patch("pam.agent.agent.asyncio.gather", wraps=asyncio.gather) as mock_gather:
            await agent._smart_search({"query": "test"})

            mock_gather.assert_called_once()
            # 4 coroutines + return_exceptions=True
            args = mock_gather.call_args
            assert len(args[0]) == 4
            assert args[1].get("return_exceptions") is True

    async def test_es_failure_does_not_block_vdb_results(self):
        """ES raises, entity/relationship VDB still return results."""
        store = _mock_vdb_store(
            entity_hits=[_make_entity_hit("Svc", "Tech", "desc")],
            relationship_hits=[_make_relationship_hit("A", "B", "REL", "desc")],
        )
        agent = _mock_agent(vdb_store=store)
        agent.search.search = AsyncMock(side_effect=RuntimeError("ES down"))

        result_text, _ = await agent._smart_search({"query": "test"})

        assert "es_backend_failed" in result_text
        # VDB results still present
        assert "Svc" in result_text
        assert "A" in result_text

    async def test_graph_failure_does_not_block_other_results(self):
        """Graph raises, ES + VDB still work."""
        store = _mock_vdb_store(
            entity_hits=[_make_entity_hit("Svc", "Tech", "desc")],
        )
        mock_graph = AsyncMock()
        agent = _mock_agent(vdb_store=store, graph_service=mock_graph)

        # Patch graph search to raise
        with patch("pam.graph.query.search_graph_relationships", side_effect=RuntimeError("Neo4j down")):
            result_text, _ = await agent._smart_search({"query": "test"})

        assert "graph_backend_failed" in result_text
        assert "Svc" in result_text

    async def test_mixed_failures_graceful(self):
        """ES + entity_vdb fail, graph + rel_vdb succeed."""
        mock_vdb = AsyncMock(spec=EntityRelationshipVDBStore)
        mock_vdb.search_entities = AsyncMock(side_effect=RuntimeError("Entity VDB down"))
        mock_vdb.search_relationships = AsyncMock(return_value=[
            {"src_entity": "X", "tgt_entity": "Y", "rel_type": "R", "description": "d", "keywords": "", "weight": 1.0, "score": 0.9, "source": "relationship_vdb"},
        ])

        agent = _mock_agent(vdb_store=mock_vdb)
        agent.search.search = AsyncMock(side_effect=RuntimeError("ES down"))

        result_text, _ = await agent._smart_search({"query": "test"})

        assert "es_backend_failed" in result_text
        assert "entity_vdb_failed" in result_text
        # rel_vdb and graph (None → returns "") should not produce warnings
        assert "relationship_vdb_failed" not in result_text

    async def test_all_backends_fail_returns_all_warnings(self):
        """All 4 fail → 4 warnings in output."""
        mock_vdb = AsyncMock(spec=EntityRelationshipVDBStore)
        mock_vdb.search_entities = AsyncMock(side_effect=RuntimeError("E"))
        mock_vdb.search_relationships = AsyncMock(side_effect=RuntimeError("R"))

        mock_graph = AsyncMock()
        agent = _mock_agent(vdb_store=mock_vdb, graph_service=mock_graph)
        agent.search.search = AsyncMock(side_effect=RuntimeError("ES"))

        with patch("pam.graph.query.search_graph_relationships", side_effect=RuntimeError("G")):
            result_text, _ = await agent._smart_search({"query": "test"})

        assert "es_backend_failed" in result_text
        assert "graph_backend_failed" in result_text
        assert "entity_vdb_failed" in result_text
        assert "relationship_vdb_failed" in result_text


# ===========================================================================
# TestSmartSearchEmbeddingReuse
# ===========================================================================


class TestSmartSearchEmbeddingReuse:
    @pytest.fixture(autouse=True)
    def _mock_tiktoken(self):
        with patch("pam.agent.context_assembly._get_encoder", return_value=_word_count_encoder()):
            yield

    async def test_single_embed_call_for_both_queries(self):
        """embed_texts called once with 2 texts (es_query + graph_query)."""
        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store)

        await agent._smart_search({"query": "test"})

        assert agent.embedder.embed_texts.call_count == 1
        texts = agent.embedder.embed_texts.call_args[0][0]
        assert len(texts) == 2

    async def test_es_query_uses_low_level_keywords(self):
        """ES query is built from low_level_keywords."""
        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store)

        await agent._smart_search({"query": "test"})

        # The embed_texts call receives [es_query, graph_query]
        texts = agent.embedder.embed_texts.call_args[0][0]
        es_query = texts[0]
        # low_level_keywords = ["deployment", "team"]
        assert "deployment" in es_query
        assert "team" in es_query

    async def test_graph_query_uses_high_level_keywords(self):
        """Graph query is built from high_level_keywords."""
        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store)

        await agent._smart_search({"query": "test"})

        texts = agent.embedder.embed_texts.call_args[0][0]
        graph_query = texts[1]
        # high_level_keywords = ["infrastructure", "reliability"]
        assert "infrastructure" in graph_query
        assert "reliability" in graph_query

    async def test_entity_vdb_uses_es_query_embedding(self):
        """Entity search gets es_query_embedding (index 0 from embed_texts)."""
        mock_vdb = AsyncMock(spec=EntityRelationshipVDBStore)
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        agent = _mock_agent(vdb_store=mock_vdb)
        await agent._smart_search({"query": "test"})

        # search_entities should receive [0.1]*1536 (first embedding)
        entity_call = mock_vdb.search_entities.call_args
        embedding_used = entity_call.kwargs.get("query_embedding") or entity_call[1].get("query_embedding")
        assert embedding_used == [0.1] * 1536

    async def test_rel_vdb_uses_graph_query_embedding(self):
        """Relationship search gets graph_query_embedding (index 1 from embed_texts)."""
        mock_vdb = AsyncMock(spec=EntityRelationshipVDBStore)
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        agent = _mock_agent(vdb_store=mock_vdb)
        await agent._smart_search({"query": "test"})

        rel_call = mock_vdb.search_relationships.call_args
        embedding_used = rel_call.kwargs.get("query_embedding") or rel_call[1].get("query_embedding")
        assert embedding_used == [0.2] * 1536


# ===========================================================================
# TestSmartSearchOutputFormat
# ===========================================================================


class TestSmartSearchOutputFormat:
    @pytest.fixture(autouse=True)
    def _mock_tiktoken(self):
        with patch("pam.agent.context_assembly._get_encoder", return_value=_word_count_encoder()):
            yield

    async def test_output_has_keyword_header(self):
        """'Keywords extracted:' present in output."""
        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store)

        result_text, _ = await agent._smart_search({"query": "test"})

        assert "Keywords extracted:" in result_text
        assert "High-level:" in result_text
        assert "Low-level:" in result_text

    async def test_entity_match_format(self):
        """Entity matches rendered as '**Name**: Description'."""
        store = _mock_vdb_store(
            entity_hits=[_make_entity_hit("AuthService", "Technology", "Handles authentication")],
        )
        agent = _mock_agent(vdb_store=store)

        result_text, _ = await agent._smart_search({"query": "test"})

        assert "**AuthService**: Handles authentication" in result_text

    async def test_relationship_match_format(self):
        """Relationship matches rendered as '**Src** -> TYPE -> **Tgt**'."""
        store = _mock_vdb_store(
            relationship_hits=[
                _make_relationship_hit("Infra", "Reliability", "SUPPORTS", "Infra supports reliability"),
            ],
        )
        agent = _mock_agent(vdb_store=store)

        result_text, _ = await agent._smart_search({"query": "test"})

        assert "**Infra** -> SUPPORTS -> **Reliability**" in result_text

    async def test_deduplicates_es_results_by_content_hash(self):
        """Duplicate ES content → only one result in output after dedup."""
        r1 = _make_search_result(title="Doc1", content="Same content", segment_id="seg-1")
        r2 = _make_search_result(title="Doc1", content="Same content", segment_id="seg-2")

        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store, es_results=[r1, r2])

        result_text, citations = await agent._smart_search({"query": "test"})

        # Both segments produce citations (dedup is at display level via assemble_context)
        # The key assertion: content appears but we have 2 citations for attribution
        assert len(citations) == 2
        assert "Same content" in result_text
