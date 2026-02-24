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
            items, "description", max_tokens=1000, max_item_tokens=5,
        )
        assert len(result) == 1  # Item kept, not dropped
        assert "..." in result[0]["description"]  # Truncated
        assert total == 1

    def test_empty_list_returns_empty(self):
        result, tokens_used, total = truncate_list_by_token_budget([], "description", max_tokens=100)
        assert result == []
        assert tokens_used == 0
        assert total == 0


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
            entities=entities, relationships=[], chunks=[],
            graph_text="", total_entities=1, total_relationships=0, total_chunks=0,
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
            entities=[], relationships=rels, chunks=[],
            graph_text="Extra graph info here", total_entities=0,
            total_relationships=1, total_chunks=0,
        )
        assert "## Knowledge Graph Relationships" in result
        assert "**A** -> USES -> **B**: uses B" in result
        assert "Extra graph info here" in result

    def test_chunks_with_source_labels(self):
        chunks = [
            {"content": "Some content", "source_label": "Guide > Auth"},
        ]
        result = _build_context_string(
            entities=[], relationships=[], chunks=chunks,
            graph_text="", total_entities=0, total_relationships=0, total_chunks=1,
        )
        assert "## Document Chunks" in result
        assert "[Source: Guide > Auth]" in result
        assert "Some content" in result

    def test_truncation_indicator(self):
        entities = [{"name": "A", "description": "desc"}]
        result = _build_context_string(
            entities=entities, relationships=[], chunks=[],
            graph_text="", total_entities=5, total_relationships=0, total_chunks=0,
        )
        assert "[+4 more entities not shown]" in result

    def test_all_empty_returns_fallback(self):
        result = _build_context_string(
            entities=[], relationships=[], chunks=[],
            graph_text="", total_entities=0, total_relationships=0, total_chunks=0,
        )
        assert result == "No relevant context found in knowledge base"

    def test_summary_header_only_mentions_nonempty(self):
        entities = [{"name": "X", "description": "desc"}]
        result = _build_context_string(
            entities=entities, relationships=[], chunks=[],
            graph_text="", total_entities=1, total_relationships=0, total_chunks=0,
        )
        assert "entities" in result.split("\n")[0]
        assert "relationships" not in result.split("\n")[0]
        assert "chunks" not in result.split("\n")[0]


# ===========================================================================
# TestAssembleContext
# ===========================================================================


class TestAssembleContext:
    def test_full_pipeline_with_all_categories(
        self, sample_es_results, sample_entities, sample_relationships,
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
            entity_tokens=2, relationship_tokens=2, max_total_tokens=10, max_item_tokens=2,
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
            es_results=[], graph_text="", entity_vdb_results=[], rel_vdb_results=[],
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
