"""Conversation summarizer — compresses long conversations into summary memories."""

from __future__ import annotations

import uuid as uuid_mod
from typing import TYPE_CHECKING

import structlog
import tiktoken
from anthropic import AsyncAnthropic

if TYPE_CHECKING:
    from pam.conversation.service import ConversationService
    from pam.memory.service import MemoryService

logger = structlog.get_logger()

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder

_SUMMARY_PROMPT = """\
Summarize this conversation into a concise paragraph that captures the key topics discussed, \
decisions made, facts learned, and any action items. Focus on information that would be \
useful context for future conversations.

Conversation:
{conversation_text}

Write a concise summary (2-4 sentences). Include specific details like names, numbers, \
and decisions — not vague descriptions."""


class ConversationSummarizer:
    """Compresses long conversations into summary memories."""

    def __init__(
        self,
        conversation_service: ConversationService,
        memory_service: MemoryService,
        anthropic_api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        summary_threshold: int = 20,
        summary_token_limit: int = 8000,
    ) -> None:
        self._conversation_service = conversation_service
        self._memory_service = memory_service
        self._client = AsyncAnthropic(api_key=anthropic_api_key)
        self._model = model
        self._summary_threshold = summary_threshold
        self._summary_token_limit = summary_token_limit

    async def should_summarize(self, conversation_id: uuid_mod.UUID):
        """Check if a conversation exceeds the summary threshold.

        Returns the ConversationDetail if summarization is needed, or None
        if it is not (to avoid re-summarizing on every subsequent message).
        """
        detail = await self._conversation_service.get(conversation_id)
        if detail is None:
            return None
        if detail.message_count < self._summary_threshold:
            return None
        # Check if we already have a summary for this conversation
        existing = await self._memory_service.search(
            query=f"conversation summary {conversation_id}",
            type_filter="conversation_summary",
            top_k=1,
        )
        for r in existing:
            meta = r.memory.metadata or {}
            if meta.get("conversation_id") == str(conversation_id):
                return None
        return detail

    async def summarize(self, conversation_id: uuid_mod.UUID, detail=None) -> str:
        """Generate a summary of the conversation and store as a memory.

        Returns the summary text, or empty string on failure.
        """
        if detail is None:
            detail = await self._conversation_service.get(conversation_id)
        if detail is None:
            return ""

        # Build conversation text, truncated to token budget
        lines = [f"{m.role}: {m.content}" for m in detail.messages]
        conversation_text = "\n".join(lines)
        encoder = _get_encoder()
        tokens = encoder.encode(conversation_text)
        if len(tokens) > self._summary_token_limit:
            conversation_text = encoder.decode(tokens[-self._summary_token_limit :])
            conversation_text = "[...earlier messages truncated...]\n" + conversation_text

        try:
            prompt = _SUMMARY_PROMPT.format(conversation_text=conversation_text)
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.content[0].text.strip()
        except Exception:
            logger.warning("summarization_llm_error", conversation_id=str(conversation_id), exc_info=True)
            return ""

        # Store as conversation_summary memory
        try:
            await self._memory_service.store(
                content=summary,
                memory_type="conversation_summary",
                source="conversation",
                metadata={"conversation_id": str(conversation_id)},
                user_id=detail.user_id,
                project_id=detail.project_id,
            )
        except Exception:
            logger.warning("summarization_store_error", exc_info=True)
            return ""

        logger.info(
            "conversation_summarized",
            conversation_id=str(conversation_id),
            summary_length=len(summary),
        )
        return summary
