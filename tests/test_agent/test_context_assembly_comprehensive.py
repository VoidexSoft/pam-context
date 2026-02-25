"""Comprehensive integration tests for Phase 14: context assembly pipeline.

Covers edge cases, budget redistribution, dedup interactions, large payloads,
graph_text integration, scoring/ordering, and end-to-end _smart_search flows.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.agent import RetrievalAgent
from pam.agent.context_assembly import (
    AssembledContext,
    ContextBudget,
    _build_context_string,
    _calculate_chunk_budget,
    assemble_context,
    count_tokens,
    deduplicate_chunks,
    truncate_list_by_token_budget,
)


# ---------------------------------------------------------------------------
# Mock tiktoken encoder
# ---------------------------------------------------------------------------


class _MockEncoder:
    """Word-split mock for tiktoken (1 word = 1 token)."""

    def encode(self, text: str) -> list[int]:
        if not text:
            return []
        return list(range(len(text.split())))

    def decode(self, tokens: list[int]) -> str:
        return " ".join(f"w{i}" for i in tokens)


@pytest.fixture(autouse=True)
def _mock_encoder():
    mock = _MockEncoder()
    with patch("pam.agent.context_assembly._get_encoder", return_value=mock):
        yield mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_es_result(**kwargs) -> SimpleNamespace:
    defaults = {
        "content": "Default content here.",
        "document_title": "Doc",
        "section_path": "Section",
        "source_url": "http://example.com",
        "segment_id": "seg-001",
        "source_id": "doc-001",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_entity(name: str, desc: str, score: float = 0.9) -> dict:
    return {"name": name, "entity_type": "Service", "description": desc, "score": score}


def _make_relationship(src: str, tgt: str, desc: str, score: float = 0.85) -> dict:
    return {
        "src_entity": src, "tgt_entity": tgt,
        "rel_type": "RELATED_TO", "description": desc, "score": score,
    }


def _build_agent(
    es_results=None, graph_text="", entity_results=None, relationship_results=None,
    vdb_store=None,
) -> RetrievalAgent:
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=es_results or [])

    mock_embedder = AsyncMock()
    mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])

    if vdb_store is None:
        vdb_store = AsyncMock()
        vdb_store.search_entities = AsyncMock(return_value=entity_results or [])
        vdb_store.search_relationships = AsyncMock(return_value=relationship_results or [])

    agent = RetrievalAgent(
        search_service=mock_search,
        embedder=mock_embedder,
        api_key="test-key",
        model="test-model",
        graph_service=None,
        vdb_store=vdb_store,
    )

    mock_text_block = MagicMock()
    mock_text_block.text = json.dumps({
        "high_level_keywords": ["test"],
        "low_level_keywords": ["query"],
    })
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    agent.client = AsyncMock()
    agent.client.messages.create = AsyncMock(return_value=mock_response)
    return agent


# ===========================================================================
# Token Budget Redistribution
# ===========================================================================


class TestBudgetRedistribution:
    """Verify unused entity/relationship tokens flow to chunk budget."""

    def test_full_unused_redistribution(self):
        """All entity+relationship budgets unused → entire max available for chunks."""
        budget = _calculate_chunk_budget(
            max_total=12000, entity_budget=4000, relationship_budget=6000,
            entity_tokens_used=0, relationship_tokens_used=0,
        )
        assert budget == 12000  # base(2000) + unused_e(4000) + unused_r(6000)

    def test_partial_entity_unused(self):
        budget = _calculate_chunk_budget(
            max_total=12000, entity_budget=4000, relationship_budget=6000,
            entity_tokens_used=1000, relationship_tokens_used=6000,
        )
        # base=2000, unused_e=3000, unused_r=0
        assert budget == 5000

    def test_over_budget_entity_capped(self):
        """If entity uses more than budgeted, unused is zero (not negative)."""
        budget = _calculate_chunk_budget(
            max_total=12000, entity_budget=4000, relationship_budget=6000,
            entity_tokens_used=5000, relationship_tokens_used=6000,
        )
        # base=2000, unused_e=max(4000-5000,0)=0, unused_r=0
        assert budget == 2000

    def test_small_max_total(self):
        """When max_total < entity+relationship budgets, base is negative, floor at 0."""
        budget = _calculate_chunk_budget(
            max_total=3000, entity_budget=4000, relationship_budget=6000,
            entity_tokens_used=0, relationship_tokens_used=0,
        )
        # base=3000-4000-6000=-7000, unused=4000+6000=10000 → max(-7000+10000, 0)=3000
        assert budget == 3000


# ===========================================================================
# Truncation Edge Cases
# ===========================================================================


class TestTruncationEdgeCases:
    """Edge cases for per-item and per-list truncation."""

    def test_single_item_exceeds_budget(self):
        """One item with 10 words, budget=3 → item truncated to fit."""
        items = [{"description": "a b c d e f g h i j"}]
        result, tokens_used, total = truncate_list_by_token_budget(
            items, "description", max_tokens=3, max_item_tokens=3,
        )
        # Item has 10 tokens, truncated to 3 tokens per item
        # After truncation: "w0 w1 w2..." = 4 tokens (3 words + "...")
        # This should still fit in budget since 3-word-truncated text ≤ 3+1 tokens
        assert len(result) <= 1
        assert total == 1

    def test_many_items_exact_budget(self):
        """Items that exactly fill the budget."""
        # Each item: 1 word = 1 token
        items = [{"description": f"word{i}"} for i in range(5)]
        result, tokens_used, total = truncate_list_by_token_budget(
            items, "description", max_tokens=5,
        )
        assert len(result) == 5
        assert tokens_used == 5
        assert total == 5

    def test_budget_zero_returns_empty(self):
        items = [{"description": "something"}]
        result, tokens_used, total = truncate_list_by_token_budget(
            items, "description", max_tokens=0,
        )
        assert result == []
        assert tokens_used == 0
        assert total == 1

    def test_missing_text_key_treated_as_empty(self):
        """Items without the text_key have 0 tokens."""
        items = [{"name": "no-desc"}, {"description": "has desc"}]
        result, tokens_used, total = truncate_list_by_token_budget(
            items, "description", max_tokens=100,
        )
        assert len(result) == 2
        assert total == 2


# ===========================================================================
# Deduplication Edge Cases
# ===========================================================================


class TestDeduplicationEdgeCases:
    def test_all_duplicates_reduced_to_one(self):
        chunks = [{"segment_id": "x", "content": f"version{i}"} for i in range(5)]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1
        assert result[0]["content"] == "version0"

    def test_empty_segment_id_not_deduped(self):
        """Empty string segment_id items are always kept."""
        chunks = [
            {"segment_id": "", "content": "a"},
            {"segment_id": "", "content": "b"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2

    def test_mixed_types_segment_id(self):
        """segment_id as int is stringified for comparison."""
        chunks = [
            {"segment_id": 123, "content": "first"},
            {"segment_id": "123", "content": "second"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1  # "123" == "123"


# ===========================================================================
# Build Context String Edge Cases
# ===========================================================================


class TestBuildContextStringEdgeCases:
    def test_all_three_sections(self):
        """Context with all three categories includes all headers."""
        result = _build_context_string(
            entities=[{"name": "E", "description": "d"}],
            relationships=[{"src_entity": "A", "tgt_entity": "B", "rel_type": "R", "description": "d"}],
            chunks=[{"content": "c", "source_label": "src"}],
            graph_text="", total_entities=1, total_relationships=1, total_chunks=1,
        )
        assert "## Knowledge Graph Entities" in result
        assert "## Knowledge Graph Relationships" in result
        assert "## Document Chunks" in result
        assert "Found 1 relevant entities, 1 relationships, 1 document chunks" in result

    def test_only_graph_text_shows_relationships_section(self):
        """graph_text alone (no VDB relationships) still shows relationship section."""
        result = _build_context_string(
            entities=[], relationships=[], chunks=[],
            graph_text="Graph context from Graphiti",
            total_entities=0, total_relationships=0, total_chunks=0,
        )
        assert "## Knowledge Graph Relationships" in result
        assert "Graph context from Graphiti" in result

    def test_dropped_counts_for_all_categories(self):
        """Truncation indicators for entities, relationships, and chunks."""
        result = _build_context_string(
            entities=[{"name": "E1", "description": "d"}],
            relationships=[{"src_entity": "A", "tgt_entity": "B", "rel_type": "R", "description": "d"}],
            chunks=[{"content": "c", "source_label": "src"}],
            graph_text="",
            total_entities=10, total_relationships=5, total_chunks=20,
        )
        assert "[+9 more entities not shown]" in result
        assert "[+4 more relationships not shown]" in result
        assert "[+19 more chunks not shown]" in result

    def test_entity_formatting(self):
        """Entity format: - **Name**: description."""
        result = _build_context_string(
            entities=[{"name": "MyService", "description": "Does things"}],
            relationships=[], chunks=[], graph_text="",
            total_entities=1, total_relationships=0, total_chunks=0,
        )
        assert "- **MyService**: Does things" in result

    def test_relationship_formatting(self):
        """Relationship format: **src** -> REL_TYPE -> **tgt**: description."""
        result = _build_context_string(
            entities=[],
            relationships=[{
                "src_entity": "ServiceA", "tgt_entity": "ServiceB",
                "rel_type": "DEPENDS_ON", "description": "A depends on B",
            }],
            chunks=[], graph_text="",
            total_entities=0, total_relationships=1, total_chunks=0,
        )
        assert "**ServiceA** -> DEPENDS_ON -> **ServiceB**: A depends on B" in result


# ===========================================================================
# Assemble Context End-to-End
# ===========================================================================


class TestAssembleContextEndToEnd:
    """Full pipeline tests with realistic data combinations."""

    def test_entities_sorted_by_score_desc(self):
        entities = [
            _make_entity("Low", "low score", score=0.3),
            _make_entity("High", "high score", score=0.9),
            _make_entity("Mid", "mid score", score=0.6),
        ]
        result = assemble_context(
            es_results=[], graph_text="",
            entity_vdb_results=entities, rel_vdb_results=[],
        )
        # High score entity should appear first in output
        high_pos = result.text.index("**High**")
        mid_pos = result.text.index("**Mid**")
        low_pos = result.text.index("**Low**")
        assert high_pos < mid_pos < low_pos

    def test_relationships_sorted_by_score_desc(self):
        rels = [
            _make_relationship("A", "B", "low relevance", score=0.3),
            _make_relationship("C", "D", "high relevance", score=0.95),
        ]
        result = assemble_context(
            es_results=[], graph_text="",
            entity_vdb_results=[], rel_vdb_results=rels,
        )
        c_pos = result.text.index("**C**")
        a_pos = result.text.index("**A**")
        assert c_pos < a_pos

    def test_duplicate_chunks_deduped(self):
        es_results = [
            _make_es_result(segment_id="seg-1", content="Same content"),
            _make_es_result(segment_id="seg-1", content="Duplicate"),
            _make_es_result(segment_id="seg-2", content="Different"),
        ]
        result = assemble_context(
            es_results=es_results, graph_text="",
            entity_vdb_results=[], rel_vdb_results=[],
        )
        # Only 2 unique chunks should appear
        assert result.text.count("[Source:") == 2

    def test_graph_text_tokens_reduce_relationship_budget(self):
        """graph_text tokens are subtracted from relationship budget."""
        # graph_text has 10 words = 10 tokens
        graph = "word " * 10
        # Relationship budget of 12 → effective rel budget = 12 - 10 = 2
        rels = [_make_relationship("A", "B", "a b c d e", score=0.9)]  # 5 tokens
        result = assemble_context(
            es_results=[], graph_text=graph,
            entity_vdb_results=[], rel_vdb_results=rels,
            budget=ContextBudget(entity_tokens=100, relationship_tokens=12, max_total_tokens=200),
        )
        # relationship_tokens_used should include graph_text tokens
        assert result.relationship_tokens_used >= 10

    def test_empty_everything_returns_fallback(self):
        result = assemble_context(
            es_results=[], graph_text="", entity_vdb_results=[], rel_vdb_results=[],
        )
        assert result.text == "No relevant context found in knowledge base"
        assert result.total_tokens == 0

    def test_assembled_context_dataclass_fields(self):
        result = assemble_context(
            es_results=[_make_es_result()], graph_text="",
            entity_vdb_results=[_make_entity("X", "desc")],
            rel_vdb_results=[],
        )
        assert isinstance(result, AssembledContext)
        assert result.entity_tokens_used >= 0
        assert result.relationship_tokens_used == 0
        assert result.chunk_tokens_used >= 0
        assert result.total_tokens == result.entity_tokens_used + result.relationship_tokens_used + result.chunk_tokens_used

    def test_tight_budget_drops_excess_items(self):
        """With very small budget, not all items fit."""
        entities = [_make_entity(f"E{i}", f"description of entity {i}") for i in range(20)]
        result = assemble_context(
            es_results=[], graph_text="",
            entity_vdb_results=entities, rel_vdb_results=[],
            budget=ContextBudget(entity_tokens=10, relationship_tokens=0, max_total_tokens=20),
        )
        # With budget of 10 tokens, we shouldn't get all 20 entities
        assert "more entities not shown" in result.text

    def test_section_path_appended_to_source_label(self):
        es = [_make_es_result(document_title="Guide", section_path="Auth > OAuth")]
        result = assemble_context(
            es_results=es, graph_text="",
            entity_vdb_results=[], rel_vdb_results=[],
        )
        assert "[Source: Guide > Auth > OAuth]" in result.text


# ===========================================================================
# Smart Search Integration (end-to-end through agent)
# ===========================================================================


class TestSmartSearchIntegration:
    """End-to-end tests through _smart_search with context assembly."""

    async def test_all_sources_combined(self):
        """smart_search combines ES, entities, relationships into structured output."""
        es = [_make_es_result(document_title="Report", section_path="Intro")]
        entities = [_make_entity("CompanyX", "A tech company")]
        rels = [_make_relationship("CompanyX", "ProductY", "produces")]
        agent = _build_agent(es_results=es, entity_results=entities, relationship_results=rels)
        text, citations = await agent._smart_search({"query": "CompanyX"})

        assert "Keywords extracted:" in text
        assert "## Knowledge Graph Entities" in text
        assert "## Knowledge Graph Relationships" in text
        assert "## Document Chunks" in text
        assert len(citations) == 1

    async def test_es_only_no_graph_sections(self):
        """With only ES results, entity/relationship sections are omitted."""
        es = [_make_es_result()]
        agent = _build_agent(es_results=es)
        text, _ = await agent._smart_search({"query": "test"})

        assert "## Document Chunks" in text
        assert "## Knowledge Graph Entities" not in text
        assert "## Knowledge Graph Relationships" not in text

    async def test_entities_only_no_chunk_section(self):
        """With only entity results, chunk section is omitted."""
        entities = [_make_entity("Svc", "a service")]
        agent = _build_agent(entity_results=entities)
        text, _ = await agent._smart_search({"query": "test"})

        assert "## Knowledge Graph Entities" in text
        assert "## Document Chunks" not in text

    async def test_vdb_failure_shows_warning(self):
        """VDB failures produce warnings but don't crash."""
        failing_vdb = AsyncMock()
        failing_vdb.search_entities = AsyncMock(side_effect=RuntimeError("boom"))
        failing_vdb.search_relationships = AsyncMock(side_effect=RuntimeError("boom"))
        agent = _build_agent(es_results=[_make_es_result()], vdb_store=failing_vdb)
        text, _ = await agent._smart_search({"query": "test"})

        assert "entity_vdb_failed" in text
        assert "relationship_vdb_failed" in text
        assert "## Document Chunks" in text  # ES still works

    async def test_no_results_at_all(self):
        """No results from any source returns fallback message."""
        agent = _build_agent()
        text, citations = await agent._smart_search({"query": "nonexistent"})

        assert "No relevant context found" in text
        assert len(citations) == 0

    async def test_citations_match_es_results(self):
        """Citations are extracted from ES results, not entities/relationships."""
        es = [
            _make_es_result(segment_id="seg-a", document_title="DocA", source_url="http://a"),
            _make_es_result(segment_id="seg-b", document_title="DocB", source_url="http://b"),
        ]
        agent = _build_agent(es_results=es, entity_results=[_make_entity("X", "d")])
        _, citations = await agent._smart_search({"query": "test"})

        assert len(citations) == 2
        assert citations[0].segment_id == "seg-a"
        assert citations[1].segment_id == "seg-b"
