"""Factory for creating LLM clients based on configuration."""

from __future__ import annotations

from pam.common.config import settings
from pam.common.llm.base import BaseLLMClient


def create_llm_client(provider: str | None = None) -> BaseLLMClient:
    """Create an LLM client for the specified (or configured) provider.

    Args:
        provider: One of "anthropic", "openai", "ollama". Defaults to settings.llm_provider.

    Returns:
        A BaseLLMClient instance.
    """
    provider = provider or settings.llm_provider

    if provider == "anthropic":
        from pam.common.llm.anthropic import AnthropicLLMClient

        return AnthropicLLMClient()
    elif provider == "openai":
        from pam.common.llm.openai import OpenAILLMClient

        return OpenAILLMClient()
    elif provider == "ollama":
        from pam.common.llm.ollama import OllamaLLMClient

        return OllamaLLMClient()
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'anthropic', 'openai', or 'ollama'.")
