"""Anthropic LLM client adapter."""

from __future__ import annotations

import base64

import structlog
from anthropic import AsyncAnthropic

from pam.common.config import settings
from pam.common.llm.base import BaseLLMClient, LLMResponse

logger = structlog.get_logger()


class AnthropicLLMClient(BaseLLMClient):
    """LLM client wrapping AsyncAnthropic."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self._model = model or settings.agent_model

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def supports_vision(self) -> bool:
        return True

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = await self._client.messages.create(**kwargs)

        text = response.content[0].text if response.content else ""
        return LLMResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self._model,
        )

    async def complete_with_vision(
        self,
        messages: list[dict],
        images: list[bytes],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        # Build content blocks with images first, then the text message
        content: list[dict] = []
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })

        # Append text from the last user message
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break
        if last_user_msg:
            content.append({"type": "text", "text": last_user_msg})

        # Replace the last user message with the multimodal content
        vision_messages = []
        replaced = False
        for msg in reversed(messages):
            if msg.get("role") == "user" and not replaced:
                vision_messages.append({"role": "user", "content": content})
                replaced = True
            else:
                vision_messages.append(msg)
        vision_messages.reverse()

        return await self.complete(vision_messages, system=system, max_tokens=max_tokens)
