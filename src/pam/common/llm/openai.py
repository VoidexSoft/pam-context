"""OpenAI LLM client adapter."""

from __future__ import annotations

import base64

import structlog
from openai import AsyncOpenAI

from pam.common.config import settings
from pam.common.llm.base import BaseLLMClient, LLMResponse

logger = structlog.get_logger()


class OpenAILLMClient(BaseLLMClient):
    """LLM client wrapping AsyncOpenAI."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self._model = model or settings.openai_llm_model

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
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,
            max_tokens=max_tokens,
        )

        text = response.choices[0].message.content or "" if response.choices else ""
        usage = response.usage
        return LLMResponse(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self._model,
        )

    async def complete_with_vision(
        self,
        messages: list[dict],
        images: list[bytes],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        content: list[dict] = []
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        # Append text from the last user message
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break
        if last_user_msg:
            content.append({"type": "text", "text": last_user_msg})

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
