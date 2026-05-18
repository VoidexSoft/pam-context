"""Fact extraction pipeline — extracts facts and preferences from conversation turns."""

from __future__ import annotations

import json
import uuid as uuid_mod
from typing import TYPE_CHECKING, cast

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import TextBlock

if TYPE_CHECKING:
    from pam.memory.service import MemoryService

logger = structlog.get_logger()

_EXTRACTION_PROMPT = """\
Analyze this conversation exchange and extract any facts, preferences, or observations \
that would be useful to remember for future conversations.

User message:
{user_message}

Assistant response:
{assistant_response}

Return a JSON array of extracted items. Each item must have:
- "type": one of "fact", "preference", "observation"
- "content": a concise statement of the extracted information

Rules:
- Only extract genuinely useful, non-trivial information
- Do NOT extract greetings, small talk, or transient questions
- Do NOT extract information that is only relevant to the current exchange
- Prefer the user's own statements for preferences
- Return an empty array [] if nothing worth remembering

Respond with ONLY the JSON array, no other text."""


class FactExtractionPipeline:
    """Extracts facts and preferences from conversation exchanges using an LLM."""

    def __init__(
        self,
        memory_service: MemoryService,
        anthropic_api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._memory_service = memory_service
        self._client = AsyncAnthropic(api_key=anthropic_api_key)
        self._model = model

    async def extract_from_exchange(
        self,
        user_message: str,
        assistant_response: str,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
    ) -> list[dict]:
        """Extract facts/preferences from a user-assistant exchange.

        Returns a list of dicts with 'type' and 'content' keys.
        Extracted items are automatically stored via MemoryService.
        """
        try:
            prompt = _EXTRACTION_PROMPT.format(
                user_message=user_message,
                assistant_response=assistant_response,
            )

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = cast(TextBlock, response.content[0]).text.strip()
            extracted = json.loads(raw_text)

            if not isinstance(extracted, list):
                logger.warning("extraction_invalid_format", raw=raw_text[:200])
                return []

        except json.JSONDecodeError:
            logger.warning("extraction_json_parse_error", exc_info=True)
            return []
        except Exception:
            logger.warning("extraction_llm_error", exc_info=True)
            return []

        # Store each extracted item via MemoryService
        stored: list[dict] = []
        for item in extracted:
            item_type = item.get("type", "fact")
            content = item.get("content", "")
            if not content:
                continue
            if item_type not in ("fact", "preference", "observation"):
                item_type = "fact"

            try:
                await self._memory_service.store(
                    content=content,
                    memory_type=item_type,
                    source="conversation",
                    user_id=user_id,
                    project_id=project_id,
                )
                stored.append(item)
            except Exception:
                logger.warning("extraction_store_error", content=content[:100], exc_info=True)

        logger.info(
            "facts_extracted",
            count=len(stored),
            user_id=str(user_id) if user_id else None,
        )
        return stored
