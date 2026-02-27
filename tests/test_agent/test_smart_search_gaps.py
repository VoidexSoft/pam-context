"""Phase 12 gap-coverage tests for _smart_search: keyword fallbacks, extraction
failure, citation extraction, null service graceful handling, and classification storage."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.agent import RetrievalAgent
from pam.agent.keyword_extractor import QueryKeywords
from pam.agent.query_classifier import ClassificationResult, RetrievalMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word_count_encoder():
    """Return a mock encoder that counts tokens as words (space-split)."""
    enc = MagicMock()
    enc.encode = lambda text: text.split()
    enc.decode = lambda tokens: " ".join(tokens)
    return enc


def _build_agent(
    graph_service=None,
    vdb_store=None,
    es_results=None,
) -> RetrievalAgent:
    """Build a minimally-mocked RetrievalAgent."""
    mock_search = AsyncMock()
    mock_search.search = AsyncMock(return_value=es_results or [])

    mock_embedder = AsyncMock()
    mock_embedder.embed_texts = AsyncMock(return_value=[[0.0] * 1536, [0.0] * 1536])

    agent = RetrievalAgent(
        search_service=mock_search,
        embedder=mock_embedder,
        api_key="test-key",
        model="test-model",
        graph_service=graph_service,
        vdb_store=vdb_store,
    )
    return agent


def _make_search_result(
    title: str = "Doc",
    section: str = "intro",
    url: str = "http://test",
    segment_id: str = "seg-1",
    content: str = "Chunk text",
) -> MagicMock:
    """Build a mock SearchResult with required attributes."""
    r = MagicMock()
    r.document_title = title
    r.section_path = section
    r.source_url = url
    r.source_id = "test-src"
    r.segment_id = segment_id
    r.content = content
    return r


# ---------------------------------------------------------------------------
# TestEmptyKeywordFallbacks
# ---------------------------------------------------------------------------


class TestEmptyKeywordFallbacks:
    """When keyword lists are empty, _smart_search falls back to original query."""

    @pytest.fixture(autouse=True)
    def _mock_encoder(self):
        with patch(
            "pam.agent.context_assembly._get_encoder",
            return_value=_word_count_encoder(),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mock_classify(self):
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=ClassificationResult(
                mode=RetrievalMode.HYBRID, confidence=0.5, method="default"
            ),
        ):
            yield

    async def test_empty_low_keywords_falls_back_to_query(self):
        """Empty low_level_keywords → ES query uses original query string."""
        agent = _build_agent()

        empty_low = QueryKeywords(
            high_level_keywords=["theme"],
            low_level_keywords=[],
        )
        with patch(
            "pam.agent.agent.extract_query_keywords",
            return_value=empty_low,
        ):
            await agent._smart_search({"query": "original question"})

        # embed_texts is called with [es_query, graph_query]
        texts = agent.embedder.embed_texts.call_args[0][0]
        es_query = texts[0]
        assert es_query == "original question"

    async def test_empty_high_keywords_falls_back_to_query(self):
        """Empty high_level_keywords → graph query uses original query string."""
        agent = _build_agent()

        empty_high = QueryKeywords(
            high_level_keywords=[],
            low_level_keywords=["entity"],
        )
        with patch(
            "pam.agent.agent.extract_query_keywords",
            return_value=empty_high,
        ):
            await agent._smart_search({"query": "original question"})

        texts = agent.embedder.embed_texts.call_args[0][0]
        graph_query = texts[1]
        assert graph_query == "original question"


# ---------------------------------------------------------------------------
# TestKeywordExtractionFailure
# ---------------------------------------------------------------------------


class TestKeywordExtractionFailure:
    """When keyword extraction fails, _smart_search returns error message."""

    @pytest.fixture(autouse=True)
    def _mock_encoder(self):
        with patch(
            "pam.agent.context_assembly._get_encoder",
            return_value=_word_count_encoder(),
        ):
            yield

    async def test_extraction_failure_returns_error_message(self):
        agent = _build_agent()

        with patch(
            "pam.agent.agent.extract_query_keywords",
            side_effect=RuntimeError("LLM call failed"),
        ):
            text, citations = await agent._smart_search({"query": "test"})

        assert "Keyword extraction failed" in text
        assert "LLM call failed" in text
        assert "search_knowledge" in text  # fallback suggestion
        assert citations == []

    async def test_extraction_json_error_returns_error_message(self):
        agent = _build_agent()

        with patch(
            "pam.agent.agent.extract_query_keywords",
            side_effect=json.JSONDecodeError("msg", "doc", 0),
        ):
            text, citations = await agent._smart_search({"query": "test"})

        assert "Keyword extraction failed" in text
        assert citations == []


# ---------------------------------------------------------------------------
# TestCitationExtraction
# ---------------------------------------------------------------------------


class TestCitationExtraction:
    """Verify citations are correctly extracted from ES results."""

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
            return_value=QueryKeywords(
                high_level_keywords=["theme"],
                low_level_keywords=["entity"],
            ),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mock_classify(self):
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=ClassificationResult(
                mode=RetrievalMode.FACTUAL, confidence=0.9, method="rules"
            ),
        ):
            yield

    async def test_citations_match_es_results(self):
        r1 = _make_search_result(title="Doc A", segment_id="seg-1")
        r2 = _make_search_result(title="Doc B", segment_id="seg-2")

        agent = _build_agent(es_results=[r1, r2])
        _, citations = await agent._smart_search({"query": "test"})

        assert len(citations) == 2
        assert citations[0].document_title == "Doc A"
        assert citations[0].segment_id == "seg-1"
        assert citations[1].document_title == "Doc B"
        assert citations[1].segment_id == "seg-2"

    async def test_no_es_results_produces_empty_citations(self):
        agent = _build_agent(es_results=[])
        _, citations = await agent._smart_search({"query": "test"})

        assert citations == []


# ---------------------------------------------------------------------------
# TestNullServiceGraceful
# ---------------------------------------------------------------------------


class TestNullServiceGraceful:
    """When graph_service or vdb_store is None, searches return empty without error."""

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
            return_value=QueryKeywords(
                high_level_keywords=["theme"],
                low_level_keywords=["entity"],
            ),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mock_classify(self):
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=ClassificationResult(
                mode=RetrievalMode.HYBRID, confidence=0.5, method="default"
            ),
        ):
            yield

    async def test_no_graph_service_returns_no_graph_warning(self):
        """graph_service=None → graph coroutine returns empty string, no warning."""
        agent = _build_agent(graph_service=None)
        text, _ = await agent._smart_search({"query": "test"})

        # No graph_backend_failed warning since the noop returned "" gracefully
        assert "graph_backend_failed" not in text

    async def test_no_vdb_store_returns_no_vdb_warning(self):
        """vdb_store=None → VDB coroutines return [], no warnings."""
        agent = _build_agent(vdb_store=None)
        text, _ = await agent._smart_search({"query": "test"})

        assert "entity_vdb_failed" not in text
        assert "relationship_vdb_failed" not in text


# ---------------------------------------------------------------------------
# TestLastClassificationStored
# ---------------------------------------------------------------------------


class TestLastClassificationStored:
    """Verify _last_classification is set after _smart_search completes."""

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
            return_value=QueryKeywords(
                high_level_keywords=["theme"],
                low_level_keywords=["entity"],
            ),
        ):
            yield

    async def test_last_classification_stored(self):
        agent = _build_agent()

        classification = ClassificationResult(
            mode=RetrievalMode.ENTITY, confidence=0.85, method="rules"
        )
        with patch(
            "pam.agent.agent.classify_query_mode",
            return_value=classification,
        ):
            await agent._smart_search({"query": "what is AuthService"})

        assert agent._last_classification is classification
        assert agent._last_classification.mode == RetrievalMode.ENTITY
        assert agent._last_classification.confidence == 0.85
