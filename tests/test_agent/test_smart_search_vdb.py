"""Tests for VDB search methods and smart_search 4-way integration."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from elasticsearch import NotFoundError

from pam.agent.agent import RetrievalAgent
from pam.common.config import Settings
from pam.ingestion.stores.entity_relationship_store import (
    EntityRelationshipVDBStore,
)


def _word_count_encoder():
    """Return a mock encoder that counts tokens as words (space-split)."""
    enc = MagicMock()
    enc.encode = lambda text: text.split()
    enc.decode = lambda tokens: " ".join(tokens)
    return enc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_es_hit(source: dict, score: float = 0.9) -> dict:
    return {"_source": source, "_score": score}


def _make_entity_hit(name: str, entity_type: str, description: str, score: float = 0.9) -> dict:
    return _make_es_hit(
        {"name": name, "entity_type": entity_type, "description": description},
        score=score,
    )


def _make_relationship_hit(
    src: str, tgt: str, rel_type: str, description: str, keywords: str = "", weight: float = 1.0, score: float = 0.85,
) -> dict:
    return _make_es_hit(
        {
            "src_entity": src,
            "tgt_entity": tgt,
            "rel_type": rel_type,
            "description": description,
            "keywords": keywords,
            "weight": weight,
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
) -> RetrievalAgent:
    """Build a minimally-mocked RetrievalAgent for smart_search testing."""
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=[])

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


# ---------------------------------------------------------------------------
# TestVDBStoreSearchMethods
# ---------------------------------------------------------------------------


class TestVDBStoreSearchMethods:
    async def test_search_entities_returns_list(self):
        store = _mock_vdb_store(
            entity_hits=[
                _make_entity_hit("AuthService", "Technology", "Handles authentication"),
                _make_entity_hit("DeployTeam", "Team", "Manages deployments"),
            ]
        )
        results = await store.search_entities(
            query_embedding=[0.1] * 1536, top_k=5
        )

        assert len(results) == 2
        assert results[0]["name"] == "AuthService"
        assert results[0]["entity_type"] == "Technology"
        assert results[0]["source"] == "entity_vdb"
        assert results[1]["name"] == "DeployTeam"
        assert results[1]["source"] == "entity_vdb"

    async def test_search_relationships_returns_list(self):
        store = _mock_vdb_store(
            relationship_hits=[
                _make_relationship_hit(
                    "AuthService", "PaymentModule", "DEPENDS_ON",
                    "Auth validates tokens for payment",
                    keywords="auth payment dependency",
                ),
            ]
        )
        results = await store.search_relationships(
            query_embedding=[0.2] * 1536, top_k=5
        )

        assert len(results) == 1
        assert results[0]["src_entity"] == "AuthService"
        assert results[0]["tgt_entity"] == "PaymentModule"
        assert results[0]["rel_type"] == "DEPENDS_ON"
        assert results[0]["source"] == "relationship_vdb"

    async def test_search_entities_handles_missing_index(self):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(
            side_effect=NotFoundError(
                message="index_not_found_exception",
                meta=MagicMock(),
                body={"error": {"type": "index_not_found_exception"}},
            )
        )
        store = EntityRelationshipVDBStore(
            client=mock_client,
            entity_index="nonexistent",
            relationship_index="nonexistent",
            embedding_dims=1536,
        )

        # Should return empty list, not raise
        results = await store.search_entities(query_embedding=[0.1] * 1536)
        assert results == []

    async def test_search_relationships_handles_missing_index(self):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(
            side_effect=NotFoundError(
                message="index_not_found_exception",
                meta=MagicMock(),
                body={"error": {"type": "index_not_found_exception"}},
            )
        )
        store = EntityRelationshipVDBStore(
            client=mock_client,
            entity_index="nonexistent",
            relationship_index="nonexistent",
            embedding_dims=1536,
        )

        results = await store.search_relationships(query_embedding=[0.2] * 1536)
        assert results == []

    async def test_search_entities_with_entity_type_filter(self):
        store = _mock_vdb_store(
            entity_hits=[
                _make_entity_hit("DeployTeam", "Team", "Manages deployments"),
            ]
        )
        results = await store.search_entities(
            query_embedding=[0.1] * 1536, top_k=5, entity_type="Team"
        )

        assert len(results) == 1
        # Verify the kNN body included a filter
        call_args = store.client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert body["knn"]["filter"] == {"term": {"entity_type": "Team"}}


# ---------------------------------------------------------------------------
# TestSmartSearchVDBIntegration
# ---------------------------------------------------------------------------


class TestSmartSearchVDBIntegration:
    @pytest.fixture(autouse=True)
    def _mock_tiktoken(self):
        """Mock tiktoken encoder so tests don't need network access."""
        with patch("pam.agent.context_assembly._get_encoder", return_value=_word_count_encoder()):
            yield

    async def test_smart_search_includes_entity_section(self):
        store = _mock_vdb_store(
            entity_hits=[
                _make_entity_hit("AuthService", "Technology", "Handles authentication"),
            ]
        )
        agent = _mock_agent(vdb_store=store)
        result_text, _citations = await agent._smart_search({"query": "deployment teams"})

        assert "## Knowledge Graph Entities" in result_text
        assert "**AuthService**: Handles authentication" in result_text

    async def test_smart_search_includes_relationship_section(self):
        store = _mock_vdb_store(
            relationship_hits=[
                _make_relationship_hit(
                    "Infra", "Reliability", "SUPPORTS",
                    "Infrastructure supports reliability goals",
                ),
            ]
        )
        agent = _mock_agent(vdb_store=store)
        result_text, _citations = await agent._smart_search({"query": "infrastructure reliability"})

        assert "## Knowledge Graph Relationships" in result_text
        assert "**Infra** -> SUPPORTS -> **Reliability**" in result_text

    async def test_smart_search_without_vdb_store_still_works(self):
        agent = _mock_agent(vdb_store=None)
        result_text, _citations = await agent._smart_search({"query": "test query"})

        # With no results from any source, assemble_context returns fallback
        assert "No relevant context found" in result_text
        # Old section names should NOT appear
        assert "## Document Results" not in result_text
        assert "## Entity Matches" not in result_text
        assert "## Relationship Matches" not in result_text

    async def test_smart_search_vdb_failure_graceful(self):
        """When VDB search raises, smart_search still returns ES+graph results with warning."""
        mock_store = AsyncMock(spec=EntityRelationshipVDBStore)
        mock_store.search_entities = AsyncMock(side_effect=RuntimeError("VDB down"))
        mock_store.search_relationships = AsyncMock(side_effect=RuntimeError("VDB down"))

        agent = _mock_agent(vdb_store=mock_store)
        result_text, _citations = await agent._smart_search({"query": "some query"})

        # Keywords header always present
        assert "Keywords extracted:" in result_text
        # VDB failures produce warnings, not crashes
        assert "entity_vdb_failed" in result_text
        assert "relationship_vdb_failed" in result_text

    async def test_smart_search_has_all_3_context_sections(self):
        """Verify all 3 structured sections appear in output when data is present."""
        store = _mock_vdb_store(
            entity_hits=[_make_entity_hit("X", "T", "desc")],
            relationship_hits=[_make_relationship_hit("A", "B", "REL", "desc")],
        )
        # Need ES results too for Document Chunks section
        agent = _mock_agent(vdb_store=store)
        # Provide mock ES results
        mock_result = MagicMock()
        mock_result.document_title = "TestDoc"
        mock_result.section_path = "intro"
        mock_result.source_url = "http://test"
        mock_result.source_id = "test-src"
        mock_result.segment_id = "seg-1"
        mock_result.content = "Test chunk content"
        agent.search.search = AsyncMock(return_value=[mock_result])

        result_text, _citations = await agent._smart_search({"query": "test"})

        assert "## Knowledge Graph Entities" in result_text
        assert "## Knowledge Graph Relationships" in result_text
        assert "## Document Chunks" in result_text

    async def test_smart_search_reuses_query_embeddings(self):
        """Verify embed_texts is called once with both queries (not per-coroutine)."""
        store = _mock_vdb_store()
        agent = _mock_agent(vdb_store=store)
        await agent._smart_search({"query": "test"})

        # embed_texts should be called exactly once with [es_query, graph_query]
        assert agent.embedder.embed_texts.call_count == 1
        call_args = agent.embedder.embed_texts.call_args[0][0]
        assert len(call_args) == 2  # two queries embedded together


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    @patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test"},
        clear=True,
    )
    def test_entity_limit_default(self):
        s = Settings(_env_file=None)
        assert s.smart_search_entity_limit == 5

    @patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test"},
        clear=True,
    )
    def test_relationship_limit_default(self):
        s = Settings(_env_file=None)
        assert s.smart_search_relationship_limit == 5
