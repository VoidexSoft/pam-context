"""Unit tests for the context assembly module (4-stage pipeline)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pam.agent.context_assembly import (
    AssembledContext,
    ContextBudget,
    _build_context_string,
    _calculate_chunk_budget,
    _truncate_text_to_tokens,
    assemble_context,
    count_tokens,
    deduplicate_chunks,
    truncate_list_by_token_budget,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _MockEncoder:
    """Word-split mock for tiktoken.Encoding (avoids network download in CI)."""

    def encode(self, text: str) -> list[int]:
        if not text:
            return []
        return list(range(len(text.split())))

    def decode(self, tokens: list[int]) -> str:
        # Not truly round-trip, but sufficient for truncation tests
        # We'll handle this by returning a string with len(tokens) words
        return " ".join(f"w{i}" for i in tokens)


@pytest.fixture(autouse=True)
def _mock_encoder():
    """Patch _get_encoder globally so tiktoken is never loaded."""
    mock = _MockEncoder()
    with patch("pam.agent.context_assembly._get_encoder", return_value=mock):
        yield mock


@pytest.fixture
def sample_entities() -> list[dict]:
    return [
        {"name": "AuthService", "entity_type": "Service", "description": "handles authentication", "score": 0.9},
        {"name": "UserModel", "entity_type": "Model", "description": "represents a user", "score": 0.8},
        {"name": "TokenManager", "entity_type": "Service", "description": "manages JWT tokens", "score": 0.7},
    ]


@pytest.fixture
def sample_relationships() -> list[dict]:
    return [
        {
            "src_entity": "AuthService",
            "tgt_entity": "UserModel",
            "rel_type": "AUTHENTICATES",
            "description": "verifies user credentials",
            "score": 0.95,
        },
        {
            "src_entity": "TokenManager",
            "tgt_entity": "AuthService",
            "rel_type": "PROVIDES_TOKENS",
            "description": "issues tokens for auth",
            "score": 0.85,
        },
    ]


@pytest.fixture
def sample_es_results() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            content="Authentication is handled via JWT tokens.",
            document_title="Architecture Guide",
            section_path="Authentication",
            source_url="https://docs.example.com/arch",
            segment_id="seg-001",
            source_id="doc-001",
        ),
        SimpleNamespace(
            content="User accounts are stored in PostgreSQL.",
            document_title="Data Model",
            section_path="Users",
            source_url="",
            segment_id="seg-002",
            source_id="doc-002",
        ),
    ]


# ===========================================================================
# TestCountTokens
# ===========================================================================


class TestCountTokens:
    def test_count_tokens_returns_int(self):
        result = count_tokens("hello world")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_empty_string(self):
        assert count_tokens("") == 0


# ===========================================================================
# TestTruncateTextToTokens
# ===========================================================================


class TestTruncateTextToTokens:
    def test_short_text_unchanged(self):
        # "hello world" = 2 tokens with mock encoder, limit 10
        result = _truncate_text_to_tokens("hello world", max_tokens=10)
        assert result == "hello world"

    def test_long_text_truncated_with_ellipsis(self):
        long_text = " ".join(f"word{i}" for i in range(20))  # 20 tokens
        result = _truncate_text_to_tokens(long_text, max_tokens=5)
        assert result.endswith("...")
        # The mock decoder produces "w0 w1 w2 w3 w4" for 5 tokens
        assert result == "w0 w1 w2 w3 w4..."

    def test_exact_limit_unchanged(self):
        text = "one two three"  # 3 tokens with mock encoder
        result = _truncate_text_to_tokens(text, max_tokens=3)
        assert result == "one two three"
        assert "..." not in result

    def test_empty_text(self):
        result = _truncate_text_to_tokens("", max_tokens=10)
        assert result == ""


# ===========================================================================
# TestTruncateListByTokenBudget
# ===========================================================================


class TestTruncateListByTokenBudget:
    def test_items_within_budget_all_kept(self):
        items = [
            {"description": "short text"},
            {"description": "another short"},
            {"description": "last one"},
        ]
        result, tokens_used, total = truncate_list_by_token_budget(items, "description", max_tokens=100)
        assert len(result) == 3
        assert total == 3
        assert tokens_used > 0

    def test_items_exceeding_budget_truncated(self):
        # Each item has 2 words = 2 tokens with mock encoder
        items = [{"description": f"word{i} text"} for i in range(5)]
        # Budget for 5 tokens = only 2 items (4 tokens), 3rd would exceed
        result, tokens_used, total = truncate_list_by_token_budget(items, "description", max_tokens=5)
        assert len(result) < 5
        assert total == 5
        assert tokens_used <= 5

    def test_individual_item_truncated_not_dropped(self):
        # Create item with very long text (>max_item_tokens words with mock)
        long_text = " ".join(f"word{i}" for i in range(20))
        items = [{"description": long_text}]
        # max_item_tokens=5 means truncate at 5 words
        result, _tokens_used, total = truncate_list_by_token_budget(
            items,
            "description",
            max_tokens=1000,
            max_item_tokens=5,
        )
        assert len(result) == 1  # Item kept, not dropped
        assert "..." in result[0]["description"]  # Truncated
        assert total == 1

    def test_empty_list_returns_empty(self):
        result, tokens_used, total = truncate_list_by_token_budget([], "description", max_tokens=100)
        assert result == []
        assert tokens_used == 0
        assert total == 0

    def test_zero_budget_returns_empty(self):
        items = [{"description": "some text"}]
        result, tokens_used, total = truncate_list_by_token_budget(items, "description", max_tokens=0)
        assert result == []
        assert tokens_used == 0
        assert total == 1

    def test_missing_text_key_treated_as_empty(self):
        # Items without the text_key contribute 0 tokens (empty string)
        items = [{"name": "no description key"}, {"description": "has text"}]
        result, tokens_used, total = truncate_list_by_token_budget(items, "description", max_tokens=100)
        assert len(result) == 2
        assert total == 2
        # First item contributes 0 tokens, second contributes >0
        assert tokens_used > 0

    def test_all_items_truncated_individually(self):
        # Each item has 20 words (20 tokens) but max_item_tokens=3
        long_text = " ".join(f"w{i}" for i in range(20))
        items = [{"description": long_text}, {"description": long_text}]
        result, _tokens_used, total = truncate_list_by_token_budget(
            items,
            "description",
            max_tokens=100,
            max_item_tokens=3,
        )
        assert len(result) == 2
        assert total == 2
        for item in result:
            assert "..." in item["description"]


# ===========================================================================
# TestDeduplicateChunks
# ===========================================================================


class TestDeduplicateChunks:
    def test_removes_duplicates_by_segment_id(self):
        chunks = [
            {"segment_id": "a", "content": "first"},
            {"segment_id": "b", "content": "second"},
            {"segment_id": "a", "content": "duplicate"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2

    def test_preserves_order(self):
        chunks = [
            {"segment_id": "a", "content": "first"},
            {"segment_id": "b", "content": "second"},
            {"segment_id": "a", "content": "duplicate"},
        ]
        result = deduplicate_chunks(chunks)
        assert result[0]["content"] == "first"
        assert result[1]["content"] == "second"

    def test_items_without_key_included(self):
        chunks = [
            {"segment_id": "a", "content": "first"},
            {"content": "no id"},
            {"segment_id": "a", "content": "duplicate"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2
        assert result[1]["content"] == "no id"

    def test_empty_list(self):
        assert deduplicate_chunks([]) == []

    def test_empty_string_key_always_included(self):
        # Items with key="" are never deduped (treated like missing key)
        chunks = [
            {"segment_id": "", "content": "first empty"},
            {"segment_id": "", "content": "second empty"},
            {"segment_id": "a", "content": "third"},
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 3

    def test_custom_key_parameter(self):
        chunks = [
            {"doc_id": "x", "content": "first"},
            {"doc_id": "y", "content": "second"},
            {"doc_id": "x", "content": "duplicate"},
        ]
        result = deduplicate_chunks(chunks, key="doc_id")
        assert len(result) == 2
        assert result[0]["content"] == "first"
        assert result[1]["content"] == "second"


# ===========================================================================
# TestCalculateChunkBudget
# ===========================================================================


class TestCalculateChunkBudget:
    def test_basic_redistribution(self):
        # entities used 2000/4000, relationships used 3000/6000, max 12000
        # base = 12000 - 4000 - 6000 = 2000
        # unused entities = 2000, unused rel = 3000
        # total = 2000 + 2000 + 3000 = 7000
        result = _calculate_chunk_budget(
            max_total=12000,
            entity_budget=4000,
            relationship_budget=6000,
            entity_tokens_used=2000,
            relationship_tokens_used=3000,
        )
        assert result == 7000

    def test_no_unused_budget(self):
        result = _calculate_chunk_budget(
            max_total=12000,
            entity_budget=4000,
            relationship_budget=6000,
            entity_tokens_used=4000,
            relationship_tokens_used=6000,
        )
        assert result == 2000  # 12000 - 4000 - 6000

    def test_floor_at_zero(self):
        result = _calculate_chunk_budget(
            max_total=5000,
            entity_budget=4000,
            relationship_budget=6000,
            entity_tokens_used=4000,
            relationship_tokens_used=6000,
        )
        assert result == 0


# ===========================================================================
# TestBuildContextString
# ===========================================================================


class TestBuildContextString:
    def test_entities_only(self):
        entities = [
            {"name": "Auth", "description": "handles auth"},
        ]
        result = _build_context_string(
            entities=entities,
            relationships=[],
            chunks=[],
            graph_text="",
            total_entities=1,
            total_relationships=0,
            total_chunks=0,
        )
        assert "## Knowledge Graph Entities" in result
        assert "- **Auth**: handles auth" in result
        assert "## Knowledge Graph Relationships" not in result
        assert "## Document Chunks" not in result

    def test_relationships_with_graph_text(self):
        rels = [
            {"src_entity": "A", "tgt_entity": "B", "rel_type": "USES", "description": "uses B"},
        ]
        result = _build_context_string(
            entities=[],
            relationships=rels,
            chunks=[],
            graph_text="Extra graph info here",
            total_entities=0,
            total_relationships=1,
            total_chunks=0,
        )
        assert "## Knowledge Graph Relationships" in result
        assert "**A** -> USES -> **B**: uses B" in result
        assert "Extra graph info here" in result

    def test_chunks_with_source_labels(self):
        chunks = [
            {"content": "Some content", "source_label": "Guide > Auth"},
        ]
        result = _build_context_string(
            entities=[],
            relationships=[],
            chunks=chunks,
            graph_text="",
            total_entities=0,
            total_relationships=0,
            total_chunks=1,
        )
        assert "## Document Chunks" in result
        assert "[Source: Guide > Auth]" in result
        assert "Some content" in result

    def test_truncation_indicator(self):
        entities = [{"name": "A", "description": "desc"}]
        result = _build_context_string(
            entities=entities,
            relationships=[],
            chunks=[],
            graph_text="",
            total_entities=5,
            total_relationships=0,
            total_chunks=0,
        )
        assert "[+4 more entities not shown]" in result

    def test_all_empty_returns_fallback(self):
        result = _build_context_string(
            entities=[],
            relationships=[],
            chunks=[],
            graph_text="",
            total_entities=0,
            total_relationships=0,
            total_chunks=0,
        )
        assert result == "No relevant context found in knowledge base"

    def test_summary_header_only_mentions_nonempty(self):
        entities = [{"name": "X", "description": "desc"}]
        result = _build_context_string(
            entities=entities,
            relationships=[],
            chunks=[],
            graph_text="",
            total_entities=1,
            total_relationships=0,
            total_chunks=0,
        )
        assert "entities" in result.split("\n")[0]
        assert "relationships" not in result.split("\n")[0]
        assert "chunks" not in result.split("\n")[0]

    def test_relationship_dropped_indicator(self):
        rels = [{"src_entity": "A", "tgt_entity": "B", "rel_type": "REL", "description": "desc"}]
        result = _build_context_string(
            entities=[],
            relationships=rels,
            chunks=[],
            graph_text="",
            total_entities=0,
            total_relationships=5,
            total_chunks=0,
        )
        assert "[+4 more relationships not shown]" in result

    def test_chunk_dropped_indicator(self):
        chunks = [{"content": "Some text", "source_label": "Doc"}]
        result = _build_context_string(
            entities=[],
            relationships=[],
            chunks=chunks,
            graph_text="",
            total_entities=0,
            total_relationships=0,
            total_chunks=3,
        )
        assert "[+2 more chunks not shown]" in result

    def test_graph_text_only_no_structured_rels(self):
        # Only graph_text, no structured relationship dicts
        result = _build_context_string(
            entities=[],
            relationships=[],
            chunks=[],
            graph_text="Some pre-formatted graph text",
            total_entities=0,
            total_relationships=0,
            total_chunks=0,
        )
        assert "## Knowledge Graph Relationships" in result
        assert "Some pre-formatted graph text" in result
        # No arrow notation since no structured relationships
        assert "->" not in result

    def test_all_three_categories_present(self):
        entities = [{"name": "E", "description": "entity desc"}]
        rels = [{"src_entity": "A", "tgt_entity": "B", "rel_type": "R", "description": "rel desc"}]
        chunks = [{"content": "chunk text", "source_label": "Doc"}]
        result = _build_context_string(
            entities=entities,
            relationships=rels,
            chunks=chunks,
            graph_text="",
            total_entities=1,
            total_relationships=1,
            total_chunks=1,
        )
        summary_line = result.split("\n")[0]
        assert "entities" in summary_line
        assert "relationships" in summary_line
        assert "chunks" in summary_line


# ===========================================================================
# TestAssembleContext
# ===========================================================================


class TestAssembleContext:
    def test_full_pipeline_with_all_categories(
        self,
        sample_es_results,
        sample_entities,
        sample_relationships,
    ):
        result = assemble_context(
            es_results=sample_es_results,
            graph_text="Graph relationship info",
            entity_vdb_results=sample_entities,
            rel_vdb_results=sample_relationships,
        )
        assert "## Knowledge Graph Entities" in result.text
        assert "## Knowledge Graph Relationships" in result.text
        assert "## Document Chunks" in result.text
        assert "Found " in result.text

    def test_budget_constrains_output(self, sample_es_results, sample_entities, sample_relationships):
        small_budget = ContextBudget(
            entity_tokens=2,
            relationship_tokens=2,
            max_total_tokens=10,
            max_item_tokens=2,
        )
        result = assemble_context(
            es_results=sample_es_results,
            graph_text="",
            entity_vdb_results=sample_entities,
            rel_vdb_results=sample_relationships,
            budget=small_budget,
        )
        unconstrained = assemble_context(
            es_results=sample_es_results,
            graph_text="",
            entity_vdb_results=sample_entities,
            rel_vdb_results=sample_relationships,
        )
        assert result.total_tokens <= unconstrained.total_tokens

    def test_empty_inputs_returns_no_context(self):
        result = assemble_context(
            es_results=[],
            graph_text="",
            entity_vdb_results=[],
            rel_vdb_results=[],
        )
        assert result.text == "No relevant context found in knowledge base"

    def test_returns_assembled_context_dataclass(self, sample_es_results, sample_entities, sample_relationships):
        result = assemble_context(
            es_results=sample_es_results,
            graph_text="",
            entity_vdb_results=sample_entities,
            rel_vdb_results=sample_relationships,
        )
        assert isinstance(result, AssembledContext)
        assert isinstance(result.text, str)
        assert isinstance(result.entity_tokens_used, int)
        assert isinstance(result.relationship_tokens_used, int)
        assert isinstance(result.chunk_tokens_used, int)
        assert isinstance(result.total_tokens, int)

    def test_graph_text_reduces_relationship_budget(self, sample_relationships):
        # Large graph_text eats into relationship budget, leaving less for VDB rels
        large_graph_text = " ".join(f"word{i}" for i in range(50))  # 50 tokens
        small_budget = ContextBudget(
            entity_tokens=100,
            relationship_tokens=55,
            max_total_tokens=500,
            max_item_tokens=100,
        )
        result = assemble_context(
            es_results=[],
            graph_text=large_graph_text,
            entity_vdb_results=[],
            rel_vdb_results=sample_relationships,
            budget=small_budget,
        )
        # graph_text=50 tokens, budget=55, so only 5 tokens left for VDB rels
        # Each rel description is ~3-4 words. Only some may fit.
        assert result.relationship_tokens_used >= 50  # At least graph_text tokens

    def test_entities_sorted_by_score_descending(self):
        entities = [
            {"name": "Low", "description": "low score", "score": 0.1},
            {"name": "High", "description": "high score", "score": 0.9},
            {"name": "Mid", "description": "mid score", "score": 0.5},
        ]
        result = assemble_context(
            es_results=[],
            graph_text="",
            entity_vdb_results=entities,
            rel_vdb_results=[],
        )
        # High score entity should appear before Low in the text
        high_pos = result.text.index("**High**")
        mid_pos = result.text.index("**Mid**")
        low_pos = result.text.index("**Low**")
        assert high_pos < mid_pos < low_pos

    def test_stage1_source_id_fallback(self):
        # ES result with no document_title falls back to source_id
        es_result = SimpleNamespace(
            content="Some content",
            document_title=None,
            section_path="",
            source_url="",
            segment_id="seg-1",
            source_id="fallback-source-id",
        )
        result = assemble_context(
            es_results=[es_result],
            graph_text="",
            entity_vdb_results=[],
            rel_vdb_results=[],
        )
        assert "[Source: fallback-source-id]" in result.text

    def test_stage1_section_path_appended(self):
        es_result = SimpleNamespace(
            content="Content here",
            document_title="My Document",
            section_path="Chapter 3",
            source_url="",
            segment_id="seg-1",
            source_id="doc-1",
        )
        result = assemble_context(
            es_results=[es_result],
            graph_text="",
            entity_vdb_results=[],
            rel_vdb_results=[],
        )
        assert "[Source: My Document > Chapter 3]" in result.text

    def test_budget_redistribution_increases_chunks(self, sample_es_results):
        # With no entities/relationships, their full budget redistributes to chunks
        no_graph_budget = ContextBudget(
            entity_tokens=4000,
            relationship_tokens=6000,
            max_total_tokens=12000,
        )
        result_with_redistribution = assemble_context(
            es_results=sample_es_results,
            graph_text="",
            entity_vdb_results=[],
            rel_vdb_results=[],
            budget=no_graph_budget,
        )
        # Chunk budget should get 12000 (all budget redistributed since no entities/rels used)
        # This means all ES results should fit
        assert result_with_redistribution.chunk_tokens_used > 0
        assert result_with_redistribution.entity_tokens_used == 0
        assert result_with_redistribution.relationship_tokens_used == 0


def test_assemble_context_with_memories():
    """assemble_context() includes memory section when memories provided."""
    memories = [
        {"content": "User prefers Python for backend work", "type": "preference", "score": 0.95},
        {"content": "Team uses PostgreSQL for analytics", "type": "fact", "score": 0.88},
    ]
    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        memory_results=memories,
    )
    assert "User Memories" in result.text
    assert "User prefers Python" in result.text
    assert "PostgreSQL" in result.text
    assert result.memory_tokens_used > 0


def test_assemble_context_with_conversation():
    """assemble_context() includes conversation section when provided."""
    conversation_context = "user: What is our Q1 target?\nassistant: The Q1 target is $10M."
    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        conversation_context=conversation_context,
    )
    assert "Recent Conversation" in result.text
    assert "Q1 target" in result.text
    assert result.conversation_tokens_used > 0


def test_assemble_context_with_all_sources():
    """assemble_context() includes all sections when all sources provided."""
    memories = [
        {"content": "User prefers concise answers", "type": "preference", "score": 0.9},
    ]
    conversation_context = "user: Summarize the report.\nassistant: Here's the summary."
    entity_results = [
        {"name": "Revenue", "entity_type": "metric", "description": "Total revenue", "score": 0.8},
    ]
    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=entity_results,
        rel_vdb_results=[],
        memory_results=memories,
        conversation_context=conversation_context,
    )
    assert "User Memories" in result.text
    assert "Recent Conversation" in result.text
    assert "Knowledge Graph Entities" in result.text


def test_assemble_context_empty_memories_omitted():
    """assemble_context() omits memory section when no memories provided."""
    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        memory_results=[],
        conversation_context="",
    )
    assert "User Memories" not in result.text
    assert "Recent Conversation" not in result.text


def test_assemble_context_memory_token_budget():
    """assemble_context() respects memory token budget."""
    memories = [
        {"content": "fact " * 500, "type": "fact", "score": 0.9},
        {"content": "another fact " * 500, "type": "fact", "score": 0.8},
    ]
    budget = ContextBudget(memory_tokens=200)
    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        memory_results=memories,
        budget=budget,
    )
    assert result.memory_tokens_used <= 250  # some overhead for headers
