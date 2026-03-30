"""Tests for smart_search tool: tool definition, keyword extraction, system prompt, config."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.agent.agent import SYSTEM_PROMPT
from pam.agent.keyword_extractor import QueryKeywords, extract_query_keywords
from pam.agent.tools import ALL_TOOLS
from pam.common.config import Settings


class TestSmartSearchToolInAllTools:
    def test_all_tools_contains_8_tools(self):
        assert len(ALL_TOOLS) == 8

    def test_smart_search_tool_present(self):
        names = [t["name"] for t in ALL_TOOLS]
        assert "smart_search" in names

    def test_smart_search_tool_schema(self):
        tool = next(t for t in ALL_TOOLS if t["name"] == "smart_search")
        assert "description" in tool
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "query" in schema["required"]


class TestKeywordExtractorParseSuccess:
    async def test_extracts_keywords_from_valid_json(self):
        mock_text_block = MagicMock()
        mock_text_block.text = json.dumps(
            {
                "high_level_keywords": ["theme"],
                "low_level_keywords": ["entity"],
            }
        )
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract_query_keywords(mock_client, "test query")
        assert isinstance(result, QueryKeywords)
        assert result.high_level_keywords == ["theme"]
        assert result.low_level_keywords == ["entity"]


class TestKeywordExtractorParseFailure:
    async def test_raises_on_invalid_json(self):
        mock_text_block = MagicMock()
        mock_text_block.text = "not valid json at all"
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with pytest.raises(json.JSONDecodeError):
            await extract_query_keywords(mock_client, "test query")


class TestSystemPromptListsSmartSearch:
    def test_smart_search_in_prompt(self):
        assert "smart_search" in SYSTEM_PROMPT

    def test_all_8_tool_names_in_prompt(self):
        expected_tools = [
            "smart_search",
            "search_knowledge",
            "get_document_context",
            "get_change_history",
            "query_database",
            "search_entities",
            "search_knowledge_graph",
            "get_entity_history",
        ]
        for tool_name in expected_tools:
            assert tool_name in SYSTEM_PROMPT, f"{tool_name} not in SYSTEM_PROMPT"

    def test_no_preference_language(self):
        lower_prompt = SYSTEM_PROMPT.lower()
        assert "preferred" not in lower_prompt
        assert "always use smart_search" not in lower_prompt


class TestConfigSmartSearchDefaults:
    @patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test"},
        clear=True,
    )
    def test_default_limits(self):
        s = Settings(_env_file=None)
        assert s.smart_search_es_limit == 5
        assert s.smart_search_graph_limit == 5
