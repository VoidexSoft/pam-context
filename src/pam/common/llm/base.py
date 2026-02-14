"""Abstract base class for LLM clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Response from an LLM completion call."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class BaseLLMClient(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a completion request."""
        ...

    async def complete_with_vision(
        self,
        messages: list[dict],
        images: list[bytes],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a completion request with images. Not all providers support this."""
        raise NotImplementedError(f"{type(self).__name__} does not support vision")

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier."""
        ...

    @property
    def supports_vision(self) -> bool:
        """Whether this client supports vision/image inputs."""
        return False
