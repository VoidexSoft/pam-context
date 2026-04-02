"""Integration tests for smart_search context assembly pipeline.

Verifies that _smart_search produces structured, token-budgeted context
via assemble_context, with correct headers, formatting, and citations.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.agent import RetrievalAgent
from pam.common.config import Settings

# ---------------------------------------------------------------------------
# Mock tiktoken encoder (word-count based, no network dependency)
# ---------------------------------------------------------------------------


def _word_count_encoder():
    """Return a mock encoder that counts tokens as words (space-split)."""
    enc = MagicMock()
    enc.encode = lambda text: text.split()
    enc.decode = lambda tokens: " ".join(tokens)
    return enc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_es_result(
    title: str = "TestDoc",
    section: str = "intro",
    url: str = "http://example.com/doc",
    source_id: str = "src-1",
    segment_id: str = "seg-1",
    content: str = "This is test document content.",
):
    """Create a mock ES SearchResult object."""
    r = MagicMock()
    r.document_title = title
    r.section_path = section
    r.source_url = url
    r.source_id = source_id
    r.segment_id = segment_id
    r.content = content
    return r


def _make_mock_entity(name: str, entity_type: str, description: str, score: float = 0.9) -> dict:
    return {
        "name": name,
        "entity_type": entity_type,
        "description": description,
        "score": score,
        "source": "entity_vdb",
    }


def _make_mock_relationship(
    src: str,
    tgt: str,
    rel_type: str,
    description: str,
    score: float = 0.85,
) -> dict:
    return {
        "src_entity": src,
        "tgt_entity": tgt,
        "rel_type": rel_type,
        "description": description,
        "score": score,
        "source": "relationship_vdb",
    }


def _build_agent(
    es_results: list | None = None,
    graph_text: str = "",
    entity_results: list[dict] | None = None,
    relationship_results: list[dict] | None = None,
    graph_service: object | None = None,
    vdb_store: object | None = None,
) -> RetrievalAgent:
    """Build a minimally-mocked RetrievalAgent for context assembly testing."""
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=es_results or [])

    mock_embedder = AsyncMock()
    mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])

    # Build VDB store mock if results are provided
    if vdb_store is None and (entity_results or relationship_results):
        vdb_store = AsyncMock()
        vdb_store.search_entities = AsyncMock(return_value=entity_results or [])
        vdb_store.search_relationships = AsyncMock(return_value=relationship_results or [])
    elif vdb_store is None:
        vdb_store = AsyncMock()
        vdb_store.search_entities = AsyncMock(return_value=[])
        vdb_store.search_relationships = AsyncMock(return_value=[])

    # Build graph service mock if text is provided
    if graph_service is None and graph_text:
        graph_service = AsyncMock()
        # Patch the graph search to return our text
    elif graph_service is None:
        graph_service = None

    agent = RetrievalAgent(
        search_service=mock_search,
        embedder=mock_embedder,
        api_key="test-key",
        model="test-model",
        graph_service=graph_service,
        vdb_store=vdb_store,
    )

    # Mock keyword extraction
    mock_text_block = MagicMock()
    mock_text_block.text = json.dumps(
        {
            "high_level_keywords": ["strategy", "trends"],
            "low_level_keywords": ["revenue", "metrics"],
        }
    )
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    agent.client = AsyncMock()
    agent.client.messages.create = AsyncMock(return_value=mock_response)

    return agent


@pytest.fixture
def es_results():
    return [
        _make_mock_es_result(
            title="Revenue Report",
            section="Q1 Summary",
            url="http://example.com/revenue",
            segment_id="seg-rev-1",
            content="Revenue grew 15% year-over-year in Q1.",
        ),
        _make_mock_es_result(
            title="Strategy Doc",
            section="Goals",
            url="http://example.com/strategy",
            segment_id="seg-str-1",
            content="Our strategic priority is market expansion.",
        ),
    ]


@pytest.fixture
def entity_results():
    return [
        _make_mock_entity("RevenueService", "Technology", "Handles revenue calculations"),
        _make_mock_entity("SalesTeam", "Team", "Responsible for enterprise sales"),
    ]


@pytest.fixture
def relationship_results():
    return [
        _make_mock_relationship(
            "SalesTeam",
            "RevenueService",
            "USES",
            "Sales team uses revenue service for forecasting",
        ),
    ]


# ---------------------------------------------------------------------------
# TestSmartSearchContextAssembly
# ---------------------------------------------------------------------------


class TestSmartSearchContextAssembly:
    """Integration tests for smart_search structured context assembly."""

    @pytest.fixture(autouse=True)
    def _mock_tiktoken(self):
        """Mock tiktoken encoder so tests don't need network access."""
        with patch(
            "pam.agent.context_assembly._get_encoder",
            return_value=_word_count_encoder(),
        ):
            yield

    async def test_output_has_structured_headers(
        self,
        es_results,
        entity_results,
        relationship_results,
    ):
        """All 3 structured section headers appear when data is present."""
        agent = _build_agent(
            es_results=es_results,
            entity_results=entity_results,
            relationship_results=relationship_results,
        )
        text, _citations = await agent._smart_search({"query": "revenue strategy"})

        assert "## Knowledge Graph Entities" in text
        assert "## Knowledge Graph Relationships" in text
        assert "## Document Chunks" in text

    async def test_output_has_summary_header(
        self,
        es_results,
        entity_results,
        relationship_results,
    ):
        """Output contains a summary line with counts."""
        agent = _build_agent(
            es_results=es_results,
            entity_results=entity_results,
            relationship_results=relationship_results,
        )
        text, _citations = await agent._smart_search({"query": "revenue strategy"})

        assert "Found 2 relevant entities" in text
        assert "1 relationships" in text
        assert "2 document chunks" in text

    async def test_output_has_keywords_header(self, es_results):
        """Output starts with keyword extraction header."""
        agent = _build_agent(es_results=es_results)
        text, _citations = await agent._smart_search({"query": "revenue"})

        assert text.startswith("Keywords extracted:")
        assert "- High-level: strategy, trends" in text
        assert "- Low-level: revenue, metrics" in text

    async def test_empty_category_omitted(self, es_results):
        """When only ES results exist, entity/relationship sections are omitted."""
        agent = _build_agent(es_results=es_results)
        text, _citations = await agent._smart_search({"query": "revenue"})

        # Document chunks should be present
        assert "## Document Chunks" in text
        # Entity and relationship sections should be absent
        assert "## Knowledge Graph Entities" not in text
        assert "## Knowledge Graph Relationships" not in text

    async def test_entity_format_bullet_list(self, entity_results):
        """Entity VDB results appear as bullet-list with bold name."""
        agent = _build_agent(entity_results=entity_results)
        text, _citations = await agent._smart_search({"query": "revenue"})

        assert "- **RevenueService**: Handles revenue calculations" in text
        assert "- **SalesTeam**: Responsible for enterprise sales" in text

    async def test_relationship_format_arrow_notation(self, relationship_results):
        """Relationship VDB results use arrow notation."""
        agent = _build_agent(relationship_results=relationship_results)
        text, _citations = await agent._smart_search({"query": "sales"})

        assert "**SalesTeam** -> USES -> **RevenueService**" in text
        assert "Sales team uses revenue service for forecasting" in text

    async def test_chunk_has_source_reference(self, es_results):
        """Document chunks include [Source: Title > Section] reference."""
        agent = _build_agent(es_results=es_results)
        text, _citations = await agent._smart_search({"query": "revenue"})

        assert "[Source: Revenue Report > Q1 Summary]" in text
        assert "[Source: Strategy Doc > Goals]" in text

    async def test_citations_still_extracted(self, es_results):
        """_smart_search still returns Citation objects from ES results."""
        agent = _build_agent(es_results=es_results)
        _text, citations = await agent._smart_search({"query": "revenue"})

        assert len(citations) == 2
        assert citations[0].document_title == "Revenue Report"
        assert citations[0].section_path == "Q1 Summary"
        assert citations[0].source_url == "http://example.com/revenue"
        assert citations[0].segment_id == "seg-rev-1"
        assert citations[1].document_title == "Strategy Doc"
        assert citations[1].segment_id == "seg-str-1"

    async def test_warnings_preserved(self, es_results):
        """When a backend fails, warning messages still appear in output."""
        # Create agent with a VDB store that raises on entity search
        failing_vdb = AsyncMock()
        failing_vdb.search_entities = AsyncMock(side_effect=RuntimeError("Entity VDB down"))
        failing_vdb.search_relationships = AsyncMock(return_value=[])

        agent = _build_agent(es_results=es_results, vdb_store=failing_vdb)
        text, _citations = await agent._smart_search({"query": "test"})

        assert "entity_vdb_failed" in text
        assert "search was unavailable, showing partial results" in text

    @patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "test",
            "ANTHROPIC_API_KEY": "test",
            "CONTEXT_ENTITY_BUDGET": "2000",
            "CONTEXT_RELATIONSHIP_BUDGET": "3000",
            "CONTEXT_MAX_TOKENS": "10000",
            "CONTEXT_MEMORY_BUDGET": "1000",
            "CONVERSATION_CONTEXT_MAX_TOKENS": "1000",
        },
        clear=True,
    )
    async def test_budget_config_from_settings(self, es_results, entity_results):
        """Budget values from Settings are passed to assemble_context."""
        from pam.common.config import reset_settings

        reset_settings()
        try:
            s = Settings(_env_file=None)
            assert s.context_entity_budget == 2000
            assert s.context_relationship_budget == 3000
            assert s.context_max_tokens == 10000

            # Use patch to intercept assemble_context and verify budget
            with patch(
                "pam.agent.agent.assemble_context",
                wraps=__import__(
                    "pam.agent.context_assembly",
                    fromlist=["assemble_context"],
                ).assemble_context,
            ) as mock_ac:
                agent = _build_agent(
                    es_results=es_results,
                    entity_results=entity_results,
                )
                await agent._smart_search({"query": "test budget"})

                assert mock_ac.called
                call_kwargs = mock_ac.call_args
                budget = call_kwargs.kwargs.get("budget") or call_kwargs[1].get("budget")
                if budget is None:
                    # Positional arg
                    budget = call_kwargs[0][4] if len(call_kwargs[0]) > 4 else None
                assert budget is not None
                assert budget.entity_tokens == 2000
                assert budget.relationship_tokens == 3000
                assert budget.max_total_tokens == 10000
        finally:
            reset_settings()
