"""Tests for the two-tier query classifier module."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.query_classifier import (
    ClassificationResult,
    RetrievalMode,
    _check_entity_mentions,
    _extract_candidate_names,
    _llm_classify,
    _rule_based_classify,
    classify_query_mode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _default_settings() -> SimpleNamespace:
    """Return a Settings-like mock with default mode config values."""
    return SimpleNamespace(
        mode_confidence_threshold=0.7,
        mode_temporal_keywords="when,history,changed,before,after,since,recently,timeline,evolution,over time",
        mode_factual_patterns="what is,define,how many,who is,list the,describe,what does,what are",
        mode_conceptual_keywords="depends on,related to,connect,impact,affects,why does,relationship,architecture,pattern,interaction",
        mode_llm_fallback_enabled=True,
    )


def _mock_llm_response(text: str) -> MagicMock:
    """Build a mock Anthropic messages.create response."""
    mock_block = MagicMock()
    mock_block.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    return mock_response


def _mock_es_response(total: int) -> dict:
    """Build a mock ES search response with a given total hit count."""
    return {
        "hits": {
            "total": {"value": total},
            "hits": [{"_source": {"name": "TestEntity"}}] if total > 0 else [],
        }
    }


# ---------------------------------------------------------------------------
# TestRetrievalMode
# ---------------------------------------------------------------------------


class TestRetrievalMode:
    def test_mode_values(self):
        """All 5 enum values exist and are strings."""
        modes = list(RetrievalMode)
        assert len(modes) == 5
        assert all(isinstance(m.value, str) for m in modes)

    def test_mode_is_str_enum(self):
        """RetrievalMode is a str enum so string comparison works."""
        assert RetrievalMode.ENTITY == "entity"
        assert RetrievalMode.CONCEPTUAL == "conceptual"
        assert RetrievalMode.TEMPORAL == "temporal"
        assert RetrievalMode.FACTUAL == "factual"
        assert RetrievalMode.HYBRID == "hybrid"


# ---------------------------------------------------------------------------
# TestRuleBasedClassify
# ---------------------------------------------------------------------------


class TestRuleBasedClassify:
    """Tests for the _rule_based_classify function."""

    def _classify(self, query: str) -> ClassificationResult:
        return _rule_based_classify(query, _default_settings())

    def test_temporal_two_keywords_high_confidence(self):
        """Two temporal keywords -> temporal with high confidence."""
        result = self._classify("When did the deployment process change recently?")
        assert result.mode == RetrievalMode.TEMPORAL
        assert result.confidence >= 0.85

    def test_temporal_one_keyword_medium_confidence(self):
        """One temporal keyword -> temporal with medium confidence."""
        result = self._classify("Show the history of AuthService")
        assert result.mode == RetrievalMode.TEMPORAL
        assert result.confidence >= 0.7

    def test_factual_what_is_pattern(self):
        """'What is' at start -> factual with high confidence."""
        result = self._classify("What is the conversion rate?")
        assert result.mode == RetrievalMode.FACTUAL
        assert result.confidence >= 0.7

    def test_factual_downgraded_by_entity_mention(self):
        """Factual pattern with entity mention -> reduced confidence."""
        result = self._classify("What teams use AuthService?")
        # Should NOT be factual with high confidence (entity mention)
        assert result.confidence < 0.7 or result.mode != RetrievalMode.FACTUAL

    def test_conceptual_two_keywords(self):
        """Two conceptual keywords -> conceptual with high confidence."""
        result = self._classify(
            "How does the service impact the payment architecture?"
        )
        assert result.mode == RetrievalMode.CONCEPTUAL
        assert result.confidence >= 0.8

    def test_conceptual_one_keyword(self):
        """One conceptual keyword -> conceptual with medium confidence."""
        result = self._classify("What relates to the API gateway?")
        # 'related to' is a conceptual keyword
        # But 'what' at start is a factual pattern -- factual negative signal
        # triggers because there is a conceptual overlap, so factual confidence=0.5
        # Then conceptual check: 'related to' gives 0.7
        # Actually, factual check happens first -- "what" is not in factual_patterns
        # "what are" and "what is" and "what does" are but "what relates" is not
        # So no factual match -> conceptual: 1 match -> 0.7
        result2 = self._classify("This is related to the deployment system")
        assert result2.mode == RetrievalMode.CONCEPTUAL
        assert result2.confidence >= 0.65

    def test_no_match_returns_hybrid(self):
        """Ambiguous query -> hybrid with low confidence."""
        result = self._classify("Tell me something interesting")
        assert result.mode == RetrievalMode.HYBRID
        assert result.confidence < 0.5

    def test_define_pattern(self):
        """'Define' at start -> factual."""
        result = self._classify("Define the SLA for tier-1 services")
        assert result.mode == RetrievalMode.FACTUAL

    def test_how_many_pattern_with_conceptual_keyword(self):
        """'How many' is factual, but 'depends on' is conceptual -> reduced confidence."""
        # "depend on" does not match "depends on" keyword exactly, so no negative signal
        result = self._classify("How many services depend on Redis?")
        assert result.mode == RetrievalMode.FACTUAL
        assert result.confidence == 0.8

        # When the exact conceptual keyword "depends on" appears, confidence is reduced
        result2 = self._classify("How many services depends on Redis?")
        assert result2.confidence < 0.7 or result2.mode != RetrievalMode.FACTUAL


# ---------------------------------------------------------------------------
# TestExtractCandidateNames
# ---------------------------------------------------------------------------


class TestExtractCandidateNames:
    def test_multi_word_capitalized(self):
        """Multi-word capitalized -> extracted."""
        candidates = _extract_candidate_names("Tell me about Auth Service")
        assert "Auth Service" in candidates

    def test_pascal_case(self):
        """PascalCase compound word -> extracted."""
        candidates = _extract_candidate_names("What does AuthService do?")
        assert "AuthService" in candidates

    def test_no_candidates_in_lowercase(self):
        """All lowercase -> no candidates."""
        candidates = _extract_candidate_names("what is the status?")
        assert candidates == []

    def test_stop_words_excluded(self):
        """Stop words are excluded from single-word candidates."""
        candidates = _extract_candidate_names("What does This mean?")
        # "What" and "This" are both stop words
        assert "What" not in candidates
        assert "This" not in candidates

    def test_multiple_candidates(self):
        """Multiple entity types extracted."""
        candidates = _extract_candidate_names(
            "How does PaymentGateway connect to Auth Service?"
        )
        assert "PaymentGateway" in candidates
        assert "Auth Service" in candidates

    def test_deduplication(self):
        """Duplicate candidates are removed."""
        candidates = _extract_candidate_names("Auth Service and Auth Service again")
        assert candidates.count("Auth Service") == 1


# ---------------------------------------------------------------------------
# TestCheckEntityMentions
# ---------------------------------------------------------------------------


class TestCheckEntityMentions:
    @pytest.mark.asyncio
    async def test_known_entity_found(self):
        """Mock ES returns 1 hit -> ENTITY mode with 0.85 confidence."""
        mock_store = MagicMock()
        mock_store.client = AsyncMock()
        mock_store.client.search = AsyncMock(return_value=_mock_es_response(1))
        mock_store.entity_index = "pam_entities"

        result = await _check_entity_mentions(
            "Tell me about Auth Service", mock_store
        )
        assert result is not None
        assert result.mode == RetrievalMode.ENTITY
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_no_entity_found(self):
        """Mock ES returns 0 hits -> None."""
        mock_store = MagicMock()
        mock_store.client = AsyncMock()
        mock_store.client.search = AsyncMock(return_value=_mock_es_response(0))
        mock_store.entity_index = "pam_entities"

        result = await _check_entity_mentions(
            "Tell me about Auth Service", mock_store
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_candidates_returns_none(self):
        """Query with no capitalized words -> None without calling ES."""
        mock_store = MagicMock()
        mock_store.client = AsyncMock()
        mock_store.entity_index = "pam_entities"

        result = await _check_entity_mentions("what is the status?", mock_store)
        assert result is None
        mock_store.client.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_es_error_returns_none(self):
        """ES raises Exception -> None (graceful degradation)."""
        mock_store = MagicMock()
        mock_store.client = AsyncMock()
        mock_store.client.search = AsyncMock(side_effect=RuntimeError("ES down"))
        mock_store.entity_index = "pam_entities"

        result = await _check_entity_mentions(
            "Tell me about Auth Service", mock_store
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_vdb_store_skipped(self):
        """Passing vdb_store=None skips entity check entirely."""
        settings = _default_settings()
        settings.mode_llm_fallback_enabled = False

        with patch(
            "pam.agent.query_classifier.get_settings", return_value=settings
        ):
            # "Tell me something" is ambiguous -> rules return hybrid 0.4
            result = await classify_query_mode(
                "Tell me something interesting",
                client=None,
                vdb_store=None,
            )
        # No vdb_store, no client -> default hybrid
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "default"


# ---------------------------------------------------------------------------
# TestLlmClassify
# ---------------------------------------------------------------------------


class TestLlmClassify:
    @pytest.mark.asyncio
    async def test_llm_returns_valid_mode(self):
        """LLM returns valid JSON -> parsed correctly."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response('{"mode": "entity", "confidence": 0.9}')
        )

        result = await _llm_classify("What is AuthService?", mock_client)
        assert result.mode == RetrievalMode.ENTITY
        assert result.confidence == 0.9
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_llm_returns_unknown_mode_defaults_hybrid(self):
        """LLM returns invalid mode value -> hybrid fallback."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response(
                '{"mode": "unknown_mode", "confidence": 0.8}'
            )
        )

        result = await _llm_classify("test query", mock_client)
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_llm_json_parse_error_defaults_hybrid(self):
        """LLM returns invalid JSON -> hybrid fallback."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response("not valid json at all")
        )

        result = await _llm_classify("test query", mock_client)
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_llm_timeout_defaults_hybrid(self):
        """LLM raises timeout -> hybrid fallback."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=TimeoutError("Request timed out")
        )

        result = await _llm_classify("test query", mock_client)
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_llm_disabled_in_settings(self):
        """LLM fallback disabled -> never called even when rules are uncertain."""
        settings = _default_settings()
        settings.mode_llm_fallback_enabled = False

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response('{"mode": "entity", "confidence": 0.95}')
        )

        with patch(
            "pam.agent.query_classifier.get_settings", return_value=settings
        ):
            result = await classify_query_mode(
                "Tell me something interesting",
                client=mock_client,
                vdb_store=None,
            )

        # Rules return hybrid 0.4, LLM is disabled -> default
        mock_client.messages.create.assert_not_called()
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "default"


# ---------------------------------------------------------------------------
# TestClassifyQueryMode (full pipeline integration)
# ---------------------------------------------------------------------------


class TestClassifyQueryMode:
    @pytest.mark.asyncio
    async def test_rules_confident_no_llm_called(self):
        """When rules are confident, LLM is never called."""
        settings = _default_settings()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock()

        with patch(
            "pam.agent.query_classifier.get_settings", return_value=settings
        ):
            result = await classify_query_mode(
                "When did the deployment change recently?",
                client=mock_client,
                vdb_store=None,
            )

        assert result.mode == RetrievalMode.TEMPORAL
        assert result.method == "rules"
        mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_rules_uncertain_llm_called(self):
        """Ambiguous query with uncertain rules -> LLM called."""
        settings = _default_settings()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response(
                '{"mode": "conceptual", "confidence": 0.85}'
            )
        )

        with patch(
            "pam.agent.query_classifier.get_settings", return_value=settings
        ):
            result = await classify_query_mode(
                "Tell me something interesting about the system",
                client=mock_client,
                vdb_store=None,
            )

        mock_client.messages.create.assert_called_once()
        assert result.mode == RetrievalMode.CONCEPTUAL
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_entity_check_confident_no_llm_called(self):
        """Entity ES lookup confident -> LLM not called."""
        settings = _default_settings()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock()

        mock_store = MagicMock()
        mock_store.client = AsyncMock()
        mock_store.client.search = AsyncMock(return_value=_mock_es_response(1))
        mock_store.entity_index = "pam_entities"

        with patch(
            "pam.agent.query_classifier.get_settings", return_value=settings
        ):
            # Query has ambiguous rules but mentions entity name
            result = await classify_query_mode(
                "Tell me about Auth Service performance",
                client=mock_client,
                vdb_store=mock_store,
            )

        assert result.mode == RetrievalMode.ENTITY
        assert result.confidence == 0.85
        mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_uncertain_defaults_hybrid(self):
        """Rules uncertain, no vdb_store, LLM low confidence -> hybrid default."""
        settings = _default_settings()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response(
                '{"mode": "entity", "confidence": 0.3}'
            )
        )

        with patch(
            "pam.agent.query_classifier.get_settings", return_value=settings
        ):
            result = await classify_query_mode(
                "Tell me something interesting",
                client=mock_client,
                vdb_store=None,
            )

        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "default"

    @pytest.mark.asyncio
    async def test_logging_called(self):
        """Verify structlog.info is called with query_mode_classified event."""
        settings = _default_settings()

        with (
            patch(
                "pam.agent.query_classifier.get_settings", return_value=settings
            ),
            patch("pam.agent.query_classifier.logger") as mock_logger,
        ):
            await classify_query_mode(
                "When did the deployment change?",
                client=None,
                vdb_store=None,
            )

        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args
        assert call_kwargs[0][0] == "query_mode_classified"
        assert "mode" in call_kwargs[1]
        assert "confidence" in call_kwargs[1]
        assert "method" in call_kwargs[1]
