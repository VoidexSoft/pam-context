"""Memory service — CRUD operations with semantic dedup and importance scoring."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from pam.common.models import Memory, MemoryResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pam.ingestion.embedders.base import BaseEmbedder
    from pam.memory.store import MemoryStore

logger = structlog.get_logger()


def _memory_to_response(memory: Memory) -> MemoryResponse:
    """Convert a Memory ORM instance to a MemoryResponse, handling metadata_ alias."""
    return MemoryResponse(
        id=memory.id,
        user_id=memory.user_id,
        project_id=memory.project_id,
        type=memory.type,
        content=memory.content,
        source=memory.source,
        metadata=memory.metadata_ if isinstance(memory.metadata_, dict) else {},
        importance=memory.importance,
        access_count=memory.access_count if memory.access_count is not None else 0,
        last_accessed_at=memory.last_accessed_at,
        expires_at=memory.expires_at,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


class MemoryService:
    """Manages discrete memories with semantic dedup and importance scoring."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: MemoryStore,
        embedder: BaseEmbedder,
        anthropic_api_key: str,
        dedup_threshold: float = 0.9,
        merge_model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._anthropic_api_key = anthropic_api_key
        self._dedup_threshold = dedup_threshold
        self._merge_model = merge_model

    async def store(
        self,
        content: str,
        memory_type: str = "fact",
        source: str | None = None,
        metadata: dict | None = None,
        importance: float = 0.5,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryResponse:
        """Store a memory with semantic deduplication.

        If a memory with cosine similarity > threshold exists for the same user,
        merges the content instead of creating a duplicate.
        """
        # Embed the content
        embeddings = await self._embedder.embed_texts([content])
        embedding = embeddings[0]

        # Check for duplicates
        duplicates = await self._store.find_duplicates(
            embedding=embedding,
            user_id=user_id,
            threshold=self._dedup_threshold,
        )

        if duplicates:
            # Merge with the most similar existing memory
            dup = duplicates[0]
            return await self._merge_and_update(
                existing_id=uuid_mod.UUID(dup["memory_id"]),
                existing_content=dup["content"],
                new_content=content,
                new_embedding=embedding,
                user_id=user_id,
                project_id=project_id,
            )

        # No duplicate — insert new memory
        memory_id = uuid_mod.uuid4()
        now = datetime.now(tz=timezone.utc)
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            project_id=project_id,
            type=memory_type,
            content=content,
            source=source,
            metadata_=metadata or {},
            importance=importance,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

        async with self._session_factory() as session:
            session.add(memory)
            await session.flush()
            await session.commit()

        # Index in ES
        await self._store.index_memory(
            memory_id=memory_id,
            content=content,
            embedding=embedding,
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
            importance=importance,
            source=source,
        )

        logger.info("memory_stored", memory_id=str(memory_id), type=memory_type, dedup="new")
        return _memory_to_response(memory)

    async def _merge_and_update(
        self,
        existing_id: uuid_mod.UUID,
        existing_content: str,
        new_content: str,
        new_embedding: list[float],
        user_id: uuid_mod.UUID | None,
        project_id: uuid_mod.UUID | None,
    ) -> MemoryResponse:
        """Merge new content into an existing memory via LLM."""
        from sqlalchemy import select

        merged_content = await self._merge_contents(existing_content, new_content)

        # Re-embed the merged content
        embeddings = await self._embedder.embed_texts([merged_content])
        merged_embedding = embeddings[0]

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == existing_id)
            )
            existing = result.scalars().first()
            if existing is None:
                logger.warning("memory_dedup_race", existing_id=str(existing_id))
                raise RuntimeError("Dedup target not found")

            existing.content = merged_content
            existing.updated_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

            # Re-index in ES
            await self._store.index_memory(
                memory_id=existing_id,
                content=merged_content,
                embedding=merged_embedding,
                user_id=user_id,
                project_id=project_id,
                memory_type=existing.type,
                importance=existing.importance,
                source=existing.source,
            )

            logger.info("memory_merged", memory_id=str(existing_id))
            return _memory_to_response(existing)

    async def _merge_contents(self, old_content: str, new_content: str) -> str:
        """Use LLM to merge overlapping memory contents."""
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=self._anthropic_api_key)
            response = await client.messages.create(
                model=self._merge_model,
                max_tokens=300,
                system=(
                    "Merge these two memories into a single, concise fact. "
                    "Keep all unique information from both. "
                    "Return only the merged text, nothing else."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Existing memory: {old_content}\n\n"
                            f"New memory: {new_content}"
                        ),
                    }
                ],
            )
            return response.content[0].text
        except Exception:
            logger.warning("memory_merge_llm_failed", exc_info=True)
            return new_content  # Fallback: use new content as-is
