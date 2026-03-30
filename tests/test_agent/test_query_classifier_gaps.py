"""Gap-coverage tests for the two-tier query classifier module.

Supplements the existing 32 tests in test_query_classifier.py with edge cases
for rule-based classification, candidate name extraction, LLM fallback, and
full pipeline integration under non-default configurations.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.query_classifier import (
    ClassificationResult,
    RetrievalMode,
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
        mode_conceptual_keywords=(
            "depends on,related to,connect,impact,affects,why does,relationship,architecture,pattern,interaction"
        ),
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
# TestRuleBasedEdgeCases
# ---------------------------------------------------------------------------


class TestRuleBasedEdgeCases:
    """Edge cases for _rule_based_classify not covered by the main test suite."""

    def _classify(self, query: str, settings=None) -> ClassificationResult:
        return _rule_based_classify(query, settings or _default_settings())

    def test_empty_and_whitespace_query_returns_hybrid(self):
        """Empty and whitespace-only queries return hybrid with low confidence."""
        result_empty = self._classify("")
        assert result_empty.mode == RetrievalMode.HYBRID
        assert result_empty.confidence < 0.5

        result_spaces = self._classify("   ")
        assert result_spaces.mode == RetrievalMode.HYBRID
        assert result_spaces.confidence < 0.5

    def test_all_untested_factual_patterns(self):
        """Factual patterns not tested elsewhere: who is, list the, describe, what does, what are."""
        for pattern_start, query in [
            ("who is", "Who is responsible for the API?"),
            ("list the", "List the available services"),
            ("describe", "Describe the deployment process"),
            ("what does", "What does the auth module do?"),
            ("what are", "What are the SLA requirements?"),
        ]:
            result = self._classify(query)
            assert result.mode == RetrievalMode.FACTUAL, (
                f"Expected FACTUAL for pattern '{pattern_start}', got {result.mode} for query: {query}"
            )
            assert result.confidence >= 0.7

    def test_custom_settings_with_different_keywords(self):
        """Non-default keyword lists work correctly."""
        settings = SimpleNamespace(
            mode_confidence_threshold=0.7,
            mode_temporal_keywords="yesterday,last week",
            mode_factual_patterns="tell me,explain",
            mode_conceptual_keywords="linked to,causes",
            mode_llm_fallback_enabled=True,
        )
        # "yesterday" is now a temporal keyword
        result = self._classify("What happened yesterday?", settings)
        assert result.mode == RetrievalMode.TEMPORAL

        # "explain" is now a factual pattern
        result2 = self._classify("Explain the process", settings)
        assert result2.mode == RetrievalMode.FACTUAL

        # "causes" is now a conceptual keyword
        result3 = self._classify("What causes the failure?", settings)
        # "what" is NOT in custom factual patterns, so no factual match
        # "causes" is conceptual -> 1 match -> 0.7
        assert result3.mode == RetrievalMode.CONCEPTUAL

    def test_keyword_parsing_with_extra_spaces_and_trailing_commas(self):
        """Keywords with extra spaces around commas are parsed correctly."""
        settings = SimpleNamespace(
            mode_confidence_threshold=0.7,
            mode_temporal_keywords="when , history , changed",
            mode_factual_patterns="what is , define",
            mode_conceptual_keywords="depends on , related to",
            mode_llm_fallback_enabled=True,
        )
        # "when" matches temporal keyword; "change?" does NOT match "changed"
        # (word boundary regex), so only 1 match -> 0.75
        result = self._classify("When did the system change?", settings)
        assert result.mode == RetrievalMode.TEMPORAL
        assert result.confidence == 0.75  # Only "when" matches

        # Use a query with two matching keywords to verify both parsed correctly
        result2 = self._classify("When did the history show it?", settings)
        assert result2.mode == RetrievalMode.TEMPORAL
        assert result2.confidence >= 0.85  # Two matches: "when" and "history"

    def test_factual_with_pascal_case_entity_triggers_negative_signal(self):
        """PascalCase entity mention reduces factual confidence below threshold."""
        # "What is" is factual pattern, "AuthService" is PascalCase -> negative signal
        result = self._classify("What is AuthService?")
        assert result.confidence < 0.7 or result.mode != RetrievalMode.FACTUAL

    def test_temporal_over_time_multiword_keyword(self):
        """The multi-word keyword 'over time' matches as a single phrase."""
        result = self._classify("How has revenue changed over time?")
        assert result.mode == RetrievalMode.TEMPORAL
        assert result.confidence >= 0.85  # Two matches: "changed" and "over time"


# ---------------------------------------------------------------------------
# TestExtractCandidateNamesEdgeCases
# ---------------------------------------------------------------------------


class TestExtractCandidateNamesEdgeCases:
    """Edge cases for _extract_candidate_names not covered by the main test suite."""

    def test_single_cap_word_at_string_start_excluded(self):
        """Capitalized word at position 0 of string is excluded by (?<!^) lookbehind."""
        candidates = _extract_candidate_names("Redis is great")
        # "Redis" is at the start of the string -> excluded by _SINGLE_CAP_RE
        # But it has no multi-word or PascalCase match either
        assert "Redis" not in candidates

    def test_three_char_minimum_enforced(self):
        """Single capitalized words must be 3+ chars (regex requires [a-z]{2,})."""
        candidates_short = _extract_candidate_names("Is Ab good?")
        assert "Ab" not in candidates_short

        candidates_ok = _extract_candidate_names("Is Abc good?")
        # "Abc" is 3 chars, not at string start, not a stop word -> included
        assert "Abc" in candidates_ok

    def test_multi_word_name_three_plus_words(self):
        """Multi-word capitalized names with 3+ words are extracted."""
        # The regex captures consecutive capitalized words as one name.
        # "The" is [A-Z][a-z]+ so "The Auth Service Gateway" is the full match.
        candidates = _extract_candidate_names("The Auth Service Gateway handles requests")
        assert "The Auth Service Gateway" in candidates

        # With a lowercase word before the entity, only the entity is captured:
        candidates2 = _extract_candidate_names("the Auth Service Gateway handles login")
        assert "Auth Service Gateway" in candidates2

    def test_all_caps_not_matched_as_pascal_case(self):
        """All-caps words (JSON, API) are NOT matched by PascalCase or multi-word cap regex."""
        candidates = _extract_candidate_names("The JSON API is fast")
        # "JSON" is all caps -> not PascalCase (requires [a-z] after first cap)
        # "API" is all caps -> not PascalCase
        # "JSON API" is not multi-word cap (multi-word cap requires [A-Z][a-z]+ pattern)
        assert "JSON" not in candidates
        assert "API" not in candidates

    def test_sentence_start_after_period_excluded(self):
        """Words at the start of a sentence (after '. ') are excluded."""
        candidates = _extract_candidate_names("Running the tests. Redis is down.")
        # "Redis" appears after ". " -> excluded by (?<!\. ) lookbehind
        assert "Redis" not in candidates


# ---------------------------------------------------------------------------
# TestLlmClassifyEdgeCases
# ---------------------------------------------------------------------------


class TestLlmClassifyEdgeCases:
    """Edge cases for _llm_classify not covered by the main test suite."""

    @pytest.mark.asyncio
    async def test_confidence_above_one_accepted(self):
        """LLM returns confidence > 1.0 — value is used as-is (no clamping)."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response('{"mode": "entity", "confidence": 1.5}')
        )
        result = await _llm_classify("What is AuthService?", mock_client)
        assert result.mode == RetrievalMode.ENTITY
        assert result.confidence == 1.5
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_empty_content_list_returns_hybrid(self):
        """LLM returns response with empty content list -> IndexError caught -> hybrid."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = []  # Empty list -> IndexError on content[0]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await _llm_classify("test query", mock_client)
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_markdown_wrapped_json_returns_hybrid(self):
        """LLM wraps JSON in markdown code fences -> JSON parse fails -> hybrid."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response('```json\n{"mode": "entity", "confidence": 0.9}\n```')
        )
        result = await _llm_classify("test query", mock_client)
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_missing_confidence_key_uses_default(self):
        """LLM returns JSON without confidence key -> defaults to 0.5."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_llm_response('{"mode": "conceptual"}'))
        result = await _llm_classify("test query", mock_client)
        assert result.mode == RetrievalMode.CONCEPTUAL
        assert result.confidence == 0.5
        assert result.method == "llm"


# ---------------------------------------------------------------------------
# TestClassifyQueryModeIntegration
# ---------------------------------------------------------------------------


class TestClassifyQueryModeIntegration:
    """Integration edge cases for the full classify_query_mode pipeline."""

    @pytest.mark.asyncio
    async def test_entity_check_below_high_threshold_triggers_llm(self):
        """Entity ES match (0.85) below high threshold (0.95) triggers LLM fallback."""
        settings = _default_settings()
        settings.mode_confidence_threshold = 0.95  # Very high threshold

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response('{"mode": "entity", "confidence": 0.96}')
        )

        mock_store = MagicMock()
        mock_store.client = AsyncMock()
        mock_store.client.search = AsyncMock(return_value=_mock_es_response(1))
        mock_store.entity_index = "pam_entities"

        with patch("pam.agent.query_classifier.get_settings", return_value=settings):
            result = await classify_query_mode(
                "Tell me about Auth Service",
                client=mock_client,
                vdb_store=mock_store,
            )

        # Entity check returns 0.85 which is < 0.95 threshold, so LLM is called
        mock_client.messages.create.assert_called_once()
        assert result.mode == RetrievalMode.ENTITY
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_low_threshold_accepts_rules_easily(self):
        """With threshold=0.3, even a low-confidence rule-based match is accepted."""
        settings = _default_settings()
        settings.mode_confidence_threshold = 0.3

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock()

        with patch("pam.agent.query_classifier.get_settings", return_value=settings):
            # Ambiguous query returns hybrid 0.4 from rules, which is > 0.3 threshold
            result = await classify_query_mode(
                "Tell me something interesting",
                client=mock_client,
                vdb_store=None,
            )

        # Rules return 0.4 which is above 0.3 threshold -> accepted
        assert result.method == "rules"
        mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_below_threshold_falls_to_default(self):
        """LLM returns valid mode but below threshold -> falls through to hybrid default."""
        settings = _default_settings()
        settings.mode_confidence_threshold = 0.7

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_llm_response('{"mode": "entity", "confidence": 0.5}')
        )

        with patch("pam.agent.query_classifier.get_settings", return_value=settings):
            result = await classify_query_mode(
                "Tell me something interesting",
                client=mock_client,
                vdb_store=None,
            )

        # Rules return 0.4, LLM returns 0.5, both below 0.7 -> default
        mock_client.messages.create.assert_called_once()
        assert result.mode == RetrievalMode.HYBRID
        assert result.method == "default"
        assert result.confidence == 0.5
