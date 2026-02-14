"""Tests for LLM abstraction layer."""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from pam.common.llm.base import BaseLLMClient, LLMResponse
from pam.common.llm.factory import create_llm_client


class TestLLMResponse:
    def test_defaults(self):
        r = LLMResponse(text="hello")
        assert r.text == "hello"
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.model == ""

    def test_full(self):
        r = LLMResponse(text="hi", input_tokens=10, output_tokens=5, model="gpt-4o")
        assert r.input_tokens == 10
        assert r.model == "gpt-4o"


class TestAnthropicLLMClient:
    @patch("pam.common.llm.anthropic.AsyncAnthropic")
    async def test_complete(self, mock_cls):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        text_block = Mock()
        text_block.text = "Hello world"
        usage = Mock()
        usage.input_tokens = 10
        usage.output_tokens = 5
        response = Mock()
        response.content = [text_block]
        response.usage = usage

        mock_client.messages.create = AsyncMock(return_value=response)

        from pam.common.llm.anthropic import AnthropicLLMClient

        client = AnthropicLLMClient(api_key="test-key", model="claude-3-haiku")
        result = await client.complete(messages=[{"role": "user", "content": "Hi"}])

        assert result.text == "Hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert client.model_name == "claude-3-haiku"
        assert client.supports_vision is True

    @patch("pam.common.llm.anthropic.AsyncAnthropic")
    async def test_complete_with_system(self, mock_cls):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        text_block = Mock()
        text_block.text = "response"
        usage = Mock()
        usage.input_tokens = 5
        usage.output_tokens = 3
        response = Mock()
        response.content = [text_block]
        response.usage = usage

        mock_client.messages.create = AsyncMock(return_value=response)

        from pam.common.llm.anthropic import AnthropicLLMClient

        client = AnthropicLLMClient(api_key="test-key")
        await client.complete(
            messages=[{"role": "user", "content": "Hi"}],
            system="You are helpful.",
        )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are helpful."


class TestOpenAILLMClient:
    @patch("pam.common.llm.openai.AsyncOpenAI")
    async def test_complete(self, mock_cls):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        choice = Mock()
        choice.message.content = "Hello from GPT"
        usage = Mock()
        usage.prompt_tokens = 15
        usage.completion_tokens = 8
        response = Mock()
        response.choices = [choice]
        response.usage = usage

        mock_client.chat.completions.create = AsyncMock(return_value=response)

        from pam.common.llm.openai import OpenAILLMClient

        client = OpenAILLMClient(api_key="test-key", model="gpt-4o")
        result = await client.complete(messages=[{"role": "user", "content": "Hi"}])

        assert result.text == "Hello from GPT"
        assert result.input_tokens == 15
        assert result.output_tokens == 8
        assert client.model_name == "gpt-4o"
        assert client.supports_vision is True


class TestOllamaLLMClient:
    async def test_complete(self):
        from pam.common.llm.ollama import OllamaLLMClient

        client = OllamaLLMClient(base_url="http://localhost:11434", model="llama3")

        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "Hello from Ollama"},
            "prompt_eval_count": 20,
            "eval_count": 10,
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_async_client

            result = await client.complete(messages=[{"role": "user", "content": "Hi"}])

        assert result.text == "Hello from Ollama"
        assert result.input_tokens == 20
        assert result.output_tokens == 10
        assert client.model_name == "llama3"
        assert client.supports_vision is True

    async def test_complete_with_system(self):
        from pam.common.llm.ollama import OllamaLLMClient

        client = OllamaLLMClient(base_url="http://localhost:11434", model="llama3")

        mock_response = Mock()
        mock_response.json.return_value = {
            "message": {"content": "response"},
            "prompt_eval_count": 5,
            "eval_count": 3,
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_async_client

            await client.complete(
                messages=[{"role": "user", "content": "Hi"}],
                system="You are helpful.",
            )

        call_args = mock_async_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}


class TestFactory:
    @patch("pam.common.llm.anthropic.settings")
    @patch("pam.common.llm.factory.settings")
    def test_create_anthropic(self, mock_factory_settings, mock_anthropic_settings):
        mock_factory_settings.llm_provider = "anthropic"
        mock_anthropic_settings.anthropic_api_key = "test"
        mock_anthropic_settings.agent_model = "claude-3-haiku"
        client = create_llm_client("anthropic")
        assert client.model_name == "claude-3-haiku"

    @patch("pam.common.llm.openai.settings")
    @patch("pam.common.llm.factory.settings")
    def test_create_openai(self, mock_factory_settings, mock_openai_settings):
        mock_factory_settings.llm_provider = "openai"
        mock_openai_settings.openai_api_key = "test"
        mock_openai_settings.openai_llm_model = "gpt-4o"
        client = create_llm_client("openai")
        assert client.model_name == "gpt-4o"

    @patch("pam.common.llm.ollama.settings")
    @patch("pam.common.llm.factory.settings")
    def test_create_ollama(self, mock_factory_settings, mock_ollama_settings):
        mock_factory_settings.llm_provider = "ollama"
        mock_ollama_settings.ollama_base_url = "http://localhost:11434"
        mock_ollama_settings.ollama_model = "llama3"
        client = create_llm_client("ollama")
        assert client.model_name == "llama3"

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_client("unknown")

    @patch("pam.common.llm.anthropic.settings")
    @patch("pam.common.llm.factory.settings")
    def test_default_provider(self, mock_factory_settings, mock_anthropic_settings):
        mock_factory_settings.llm_provider = "anthropic"
        mock_anthropic_settings.anthropic_api_key = "test"
        mock_anthropic_settings.agent_model = "claude-3-haiku"
        client = create_llm_client()  # No provider arg — uses settings
        assert client.model_name == "claude-3-haiku"


class TestEntityExtractorWithLLMClient:
    """Test that EntityExtractor works with the BaseLLMClient interface."""

    async def test_extract_with_llm_client(self):
        from pam.common.llm.base import LLMResponse
        from pam.ingestion.extractors.entity_extractor import EntityExtractor

        mock_client = AsyncMock(spec=BaseLLMClient)
        mock_client.complete = AsyncMock(return_value=LLMResponse(
            text=json.dumps([{
                "entity_type": "metric_definition",
                "entity_data": {"name": "DAU"},
                "confidence": 0.9,
            }]),
            input_tokens=100,
            output_tokens=50,
        ))

        extractor = EntityExtractor(llm_client=mock_client)
        results = await extractor.extract_from_text("DAU is daily active users.")

        assert len(results) == 1
        assert results[0].entity_type == "metric_definition"
        mock_client.complete.assert_called_once()
