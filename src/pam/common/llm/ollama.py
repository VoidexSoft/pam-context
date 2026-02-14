"""Ollama LLM client adapter."""

from __future__ import annotations

import base64

import httpx
import structlog

from pam.common.config import settings
from pam.common.llm.base import BaseLLMClient, LLMResponse

logger = structlog.get_logger()


class OllamaLLMClient(BaseLLMClient):
    """LLM client using Ollama's REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_model

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def supports_vision(self) -> bool:
        return True  # Ollama supports vision for compatible models (llava, etc.)

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

        payload = {
            "model": self._model,
            "messages": all_messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._model,
        )

    async def complete_with_vision(
        self,
        messages: list[dict],
        images: list[bytes],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        # Ollama supports images via the "images" field in message content
        b64_images = [base64.b64encode(img).decode() for img in images]

        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        vision_messages = []
        replaced = False
        for msg in reversed(messages):
            if msg.get("role") == "user" and not replaced:
                vision_messages.append({
                    "role": "user",
                    "content": last_user_msg,
                    "images": b64_images,
                })
                replaced = True
            else:
                vision_messages.append(msg)
        vision_messages.reverse()

        return await self.complete(vision_messages, system=system, max_tokens=max_tokens)
