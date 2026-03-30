"""Unit tests for keyword_extractor: .get() defaults, error paths, prompt, timeout."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.agent.keyword_extractor import (
    QueryKeywords,
    extract_query_keywords,
)


def _mock_client_returning(text: str) -> AsyncMock:
    """Build mock AsyncAnthropic client that returns the given text."""
    mock_text_block = MagicMock()
    mock_text_block.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=mock_response)
    return client


class TestGetDefaults:
    """Verify .get() returns empty list when JSON keys are missing."""

    async def test_missing_high_level_key_returns_empty_list(self):
        client = _mock_client_returning(
            json.dumps(
                {
                    "low_level_keywords": ["entity"],
                }
            )
        )

        result = await extract_query_keywords(client, "test query")

        assert isinstance(result, QueryKeywords)
        assert result.high_level_keywords == []
        assert result.low_level_keywords == ["entity"]

    async def test_missing_low_level_key_returns_empty_list(self):
        client = _mock_client_returning(
            json.dumps(
                {
                    "high_level_keywords": ["theme"],
                }
            )
        )

        result = await extract_query_keywords(client, "test query")

        assert isinstance(result, QueryKeywords)
        assert result.high_level_keywords == ["theme"]
        assert result.low_level_keywords == []


class TestErrorPaths:
    """Verify exceptions re-raise correctly."""

    async def test_empty_response_content_raises_index_error(self):
        mock_response = MagicMock()
        mock_response.content = []

        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_response)

        with pytest.raises(IndexError):
            await extract_query_keywords(client, "test query")

    async def test_general_exception_reraises(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("API timeout"))

        with pytest.raises(RuntimeError, match="API timeout"):
            await extract_query_keywords(client, "test query")


class TestPromptAndTimeout:
    """Verify prompt formatting and timeout forwarding."""

    async def test_prompt_contains_query(self):
        client = _mock_client_returning(
            json.dumps(
                {
                    "high_level_keywords": ["a"],
                    "low_level_keywords": ["b"],
                }
            )
        )

        await extract_query_keywords(client, "What services depend on auth?")

        call_kwargs = client.messages.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1]["messages"]
        prompt_text = messages[0]["content"]
        assert "What services depend on auth?" in prompt_text

    async def test_timeout_parameter_forwarded(self):
        client = _mock_client_returning(
            json.dumps(
                {
                    "high_level_keywords": [],
                    "low_level_keywords": [],
                }
            )
        )

        await extract_query_keywords(client, "test", timeout=7.5)

        call_kwargs = client.messages.create.call_args
        timeout_val = call_kwargs.kwargs.get("timeout") or call_kwargs[1]["timeout"]
        assert timeout_val == 7.5
