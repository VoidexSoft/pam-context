"""Integration tests for mode-based routing in smart_search.

Verifies that the query classifier is wired into _smart_search and that
classified modes control which retrieval paths actually execute.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

from pam.agent.agent import RetrievalAgent
from pam.agent.query_classifier import ClassificationResult, RetrievalMode
from pam.api.routes.chat import ChatResponse


def _tool_use_block(tool_id: str, tool_name: str, tool_input: dict):
    """Create a tool_use content block that works with attribute access.

    MagicMock(name=...) sets the mock's repr name, not an attribute,
    so we use SimpleNamespace instead.
    """
    return SimpleNamespace(type="tool_use", id=tool_id, name=tool_name, input=tool_input)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word_count_encoder():
    """Return a mock encoder that counts tokens as words (space-split)."""
    enc = MagicMock()
    enc.encode = lambda text: text.split()
    enc.decode = lambda tokens: " ".join(tokens)
    return enc


def _mock_keywords():
    """Return a fixed QueryKeywords result."""
    from pam.agent.keyword_extractor import QueryKeywords

    return QueryKeywords(
        high_level_keywords=["strategy", "trends"],
        low_level_keywords=["revenue", "metrics"],
    )


def _build_agent(
    graph_service=None,
    vdb_store=None,
) -> RetrievalAgent:
    """Build a minimally-mocked RetrievalAgent for mode routing tests."""
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=[])

    mock_embedder = AsyncMock()
    mock_embedder.embed_texts = AsyncMock(return_value=[[0.0] * 1536, [0.0] * 1536])

    if vdb_store is None:
        vdb_store = AsyncMock()
        vdb_store.search_entities = AsyncMock(return_value=[])
        vdb_store.search_relationships = AsyncMock(return_value=[])

    agent = RetrievalAgent(
        search_service=mock_search,
        embedder=mock_embedder,
        api_key="test-key",
        model="test-model",
        graph_service=graph_service,
        vdb_store=vdb_store,
    )

    return agent


# ---------------------------------------------------------------------------
# TestModeRouting
# ---------------------------------------------------------------------------


class TestModeRouting:
    """Verify that classified mode controls which search backends run."""

    @pytest.fixture(autouse=True)
    def _mock_encoder(self):
        """Mock tiktoken encoder for context assembly."""
        with patch(
            "pam.agent.context_assembly._get_encoder",
            return_value=_word_count_encoder(),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mock_kw(self):
        """Mock keyword extraction to skip real API call."""
        with patch(
            "pam.agent.agent.extract_query_keywords",
            return_value=_mock_keywords(),
        ):
            yield

    async def test_factual_mode_skips_graph_and_vdb(self):
        """FACTUAL mode: only ES search runs; graph, entity VDB, rel VDB skipped."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        mock_graph = AsyncMock()
        agent = _build_agent(graph_service=mock_graph, vdb_store=mock_vdb)

        classification = ClassificationResult(
            mode=RetrievalMode.FACTUAL, confidence=0.85, method="rules"
        )
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ):
            await agent._smart_search({"query": "what is revenue"})

        # ES search should have been called
        assert agent.search.search.called
        # VDB searches should NOT have been called (noop coroutines used instead)
        assert not mock_vdb.search_entities.called
        assert not mock_vdb.search_relationships.called

    async def test_entity_mode_runs_es_and_entity_vdb_only(self):
        """ENTITY mode: ES + entity VDB run; graph and rel VDB skipped."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        mock_graph = AsyncMock()
        agent = _build_agent(graph_service=mock_graph, vdb_store=mock_vdb)

        classification = ClassificationResult(
            mode=RetrievalMode.ENTITY, confidence=0.85, method="rules"
        )
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ):
            await agent._smart_search({"query": "what is AuthService"})

        assert agent.search.search.called
        assert mock_vdb.search_entities.called
        assert not mock_vdb.search_relationships.called

    async def test_conceptual_mode_runs_es_graph_and_rel_vdb(self):
        """CONCEPTUAL mode: ES + graph + rel VDB run; entity VDB skipped."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        mock_graph = AsyncMock()
        agent = _build_agent(graph_service=mock_graph, vdb_store=mock_vdb)

        classification = ClassificationResult(
            mode=RetrievalMode.CONCEPTUAL, confidence=0.85, method="rules"
        )
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ), patch(
            "pam.graph.query.search_graph_relationships",
            new_callable=AsyncMock,
            return_value="graph results",
        ) as mock_graph_search:
            await agent._smart_search({"query": "how do services depend on each other"})

        assert agent.search.search.called
        assert mock_graph_search.called
        assert mock_vdb.search_relationships.called
        assert not mock_vdb.search_entities.called

    async def test_hybrid_mode_runs_all_paths(self):
        """HYBRID mode: all 4 search paths run."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        mock_graph = AsyncMock()
        agent = _build_agent(graph_service=mock_graph, vdb_store=mock_vdb)

        classification = ClassificationResult(
            mode=RetrievalMode.HYBRID, confidence=0.5, method="default"
        )
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ), patch(
            "pam.graph.query.search_graph_relationships",
            new_callable=AsyncMock,
            return_value="graph results",
        ) as mock_graph_search:
            await agent._smart_search({"query": "tell me everything about the system"})

        assert agent.search.search.called
        assert mock_graph_search.called
        assert mock_vdb.search_entities.called
        assert mock_vdb.search_relationships.called

    async def test_temporal_mode_runs_all_paths(self):
        """TEMPORAL mode: all 4 search paths run."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        mock_graph = AsyncMock()
        agent = _build_agent(graph_service=mock_graph, vdb_store=mock_vdb)

        classification = ClassificationResult(
            mode=RetrievalMode.TEMPORAL, confidence=0.9, method="rules"
        )
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ), patch(
            "pam.graph.query.search_graph_relationships",
            new_callable=AsyncMock,
            return_value="graph results",
        ) as mock_graph_search:
            await agent._smart_search({"query": "how has AuthService changed since January"})

        assert agent.search.search.called
        assert mock_graph_search.called
        assert mock_vdb.search_entities.called
        assert mock_vdb.search_relationships.called

    async def test_forced_mode_from_tool_input(self):
        """When mode is passed in tool input, classification is bypassed."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        agent = _build_agent(vdb_store=mock_vdb)

        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=ClassificationResult(
                mode=RetrievalMode.HYBRID, confidence=0.5, method="default"
            ),
        ) as mock_classify:
            await agent._smart_search({"query": "test query", "mode": "factual"})

        # classify_query_mode should NOT have been called
        assert not mock_classify.called
        # ES should run (factual mode includes ES)
        assert agent.search.search.called
        # VDB searches should NOT run (factual mode skips them)
        assert not mock_vdb.search_entities.called
        assert not mock_vdb.search_relationships.called

    async def test_invalid_forced_mode_falls_back_to_classification(self):
        """Invalid mode string in tool input falls back to auto-classification."""
        mock_vdb = AsyncMock()
        mock_vdb.search_entities = AsyncMock(return_value=[])
        mock_vdb.search_relationships = AsyncMock(return_value=[])

        agent = _build_agent(vdb_store=mock_vdb)

        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=ClassificationResult(
                mode=RetrievalMode.HYBRID, confidence=0.5, method="default"
            ),
        ) as mock_classify:
            await agent._smart_search({"query": "test query", "mode": "invalid_mode"})

        # classify_query_mode SHOULD have been called (fallback)
        assert mock_classify.called


# ---------------------------------------------------------------------------
# TestModeMetadataPropagation
# ---------------------------------------------------------------------------


class TestModeMetadataPropagation:
    """Verify mode metadata flows to AgentResponse, ChatResponse, and SSE events."""

    @pytest.fixture(autouse=True)
    def _mock_encoder(self):
        with patch(
            "pam.agent.context_assembly._get_encoder",
            return_value=_word_count_encoder(),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mock_kw(self):
        with patch(
            "pam.agent.agent.extract_query_keywords",
            return_value=_mock_keywords(),
        ):
            yield

    async def test_agent_response_has_mode_metadata(self):
        """AgentResponse carries retrieval_mode and mode_confidence from classification."""
        agent = _build_agent()

        classification = ClassificationResult(
            mode=RetrievalMode.FACTUAL, confidence=0.85, method="rules"
        )

        # First LLM call: tool_use with smart_search
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_response.content = [
            _tool_use_block("tool_1", "smart_search", {"query": "what is revenue"}),
        ]

        # Second call returns end_turn with the answer
        mock_final_response = MagicMock()
        mock_final_response.stop_reason = "end_turn"
        mock_final_response.usage = MagicMock(input_tokens=200, output_tokens=100)
        mock_final_text = MagicMock()
        mock_final_text.text = "Revenue is money earned."
        mock_final_text.type = "text"
        mock_final_response.content = [mock_final_text]

        agent.client = AsyncMock()
        agent.client.messages.create = AsyncMock(
            side_effect=[mock_response, mock_final_response]
        )

        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ):
            result = await agent.answer("what is revenue")

        assert result.retrieval_mode == "factual"
        assert result.mode_confidence == 0.85

    async def test_chat_response_model_has_mode_fields(self):
        """ChatResponse can be constructed with retrieval_mode and mode_confidence."""
        resp = ChatResponse(
            response="test answer",
            citations=[],
            conversation_id=None,
            token_usage={},
            latency_ms=100.0,
            retrieval_mode="factual",
            mode_confidence=0.85,
        )
        assert resp.retrieval_mode == "factual"
        assert resp.mode_confidence == 0.85

        # Test serialization
        data = resp.model_dump()
        assert data["retrieval_mode"] == "factual"
        assert data["mode_confidence"] == 0.85

    async def test_chat_response_mode_fields_optional(self):
        """ChatResponse works without mode fields (backward compatibility)."""
        resp = ChatResponse(
            response="test",
            citations=[],
            conversation_id=None,
            token_usage={},
            latency_ms=0,
        )
        assert resp.retrieval_mode is None
        assert resp.mode_confidence is None

    async def test_streaming_done_event_has_mode_metadata(self):
        """SSE done event includes retrieval_mode and mode_confidence in metadata."""
        agent = _build_agent()

        classification = ClassificationResult(
            mode=RetrievalMode.ENTITY, confidence=0.9, method="rules"
        )

        # Mock LLM to do tool_use -> smart_search -> end_turn
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.usage = MagicMock(input_tokens=100, output_tokens=50)
        mock_tool_response.content = [
            _tool_use_block("tool_1", "smart_search", {"query": "what is AuthService"}),
        ]

        mock_final_response = MagicMock()
        mock_final_response.stop_reason = "end_turn"
        mock_final_response.usage = MagicMock(input_tokens=200, output_tokens=100)
        mock_final_text = MagicMock()
        mock_final_text.text = "AuthService handles authentication."
        mock_final_text.type = "text"
        mock_final_response.content = [mock_final_text]

        agent.client = AsyncMock()
        agent.client.messages.create = AsyncMock(
            side_effect=[mock_tool_response, mock_final_response]
        )

        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ):
            events = []
            async for event in agent.answer_streaming("what is AuthService"):
                events.append(event)

        # Find the done event
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1

        metadata = done_events[0]["metadata"]
        assert metadata["retrieval_mode"] == "entity"
        assert metadata["mode_confidence"] == 0.9


# ---------------------------------------------------------------------------
# TestModeLogging
# ---------------------------------------------------------------------------


class TestModeLogging:
    """Verify classification is logged via structlog."""

    @pytest.fixture(autouse=True)
    def _mock_encoder(self):
        with patch(
            "pam.agent.context_assembly._get_encoder",
            return_value=_word_count_encoder(),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mock_kw(self):
        with patch(
            "pam.agent.agent.extract_query_keywords",
            return_value=_mock_keywords(),
        ):
            yield

    async def test_classification_logged(self):
        """smart_search_mode_selected event is logged with mode, confidence, method."""
        agent = _build_agent()

        classification = ClassificationResult(
            mode=RetrievalMode.FACTUAL, confidence=0.8, method="rules"
        )

        log_events: list[dict] = []

        def capture_log(_logger, method_name, event_dict):
            log_events.append(event_dict.copy())
            raise structlog.DropEvent

        # Haystack (and other libs) call structlog.configure() on import,
        # replacing the processor list and enabling logger caching. This
        # means capture_logs() and module-level loggers operate on
        # different list objects. Instead, we patch the logger directly
        # with a freshly-bound one using our capture processor.
        test_logger = structlog.wrap_logger(
            None,
            processors=[capture_log],
            wrapper_class=structlog.make_filtering_bound_logger(0),
        )

        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ), patch("pam.agent.agent.logger", test_logger):
            await agent._smart_search({"query": "what is the definition of revenue"})

        mode_events = [
            e for e in log_events if e.get("event") == "smart_search_mode_selected"
        ]
        assert len(mode_events) >= 1, f"Expected mode log event, got: {log_events}"
        evt = mode_events[0]
        assert evt["mode"] == "factual"
        assert evt["confidence"] == 0.8
        assert evt["method"] == "rules"
