"""Memory service — CRUD operations with semantic dedup and importance scoring."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from pam.common.models import Memory, MemoryResponse, MemorySearchResult

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
        # Input validation
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty")
        if len(content) > 10_000:
            raise ValueError("Memory content exceeds 10,000 character limit")
        content = content.strip()

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
                new_importance=importance,
                new_source=source,
                new_metadata=metadata,
                new_expires_at=expires_at,
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
        new_importance: float | None = None,
        new_source: str | None = None,
        new_metadata: dict | None = None,
        new_expires_at: datetime | None = None,
    ) -> MemoryResponse:
        """Merge new content into an existing memory via LLM.

        Also forwards importance, source, metadata, and expires_at from
        the incoming store() call so they are not silently discarded.
        """
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
            if new_importance is not None:
                existing.importance = new_importance
            if new_source is not None:
                existing.source = new_source
            if new_metadata is not None:
                existing.metadata_ = new_metadata
            if new_expires_at is not None:
                existing.expires_at = new_expires_at
            await session.flush()
            await session.commit()

            # Snapshot values before session closes
            response = _memory_to_response(existing)
            mem_type = existing.type
            mem_importance = existing.importance
            mem_source = existing.source

        # Re-index in ES (outside session to avoid holding DB connection)
        await self._store.index_memory(
            memory_id=existing_id,
            content=merged_content,
            embedding=merged_embedding,
            user_id=user_id,
            project_id=project_id,
            memory_type=mem_type,
            importance=mem_importance,
            source=mem_source,
        )

        logger.info("memory_merged", memory_id=str(existing_id))
        return response

    @staticmethod
    def compute_importance(
        created_at: datetime,
        access_count: int,
        explicit_weight: float,
        max_age_days: float = 90.0,
    ) -> float:
        """Compute importance score per spec formula.

        importance = 0.5 * recency + 0.3 * access_frequency + 0.2 * explicit_weight

        recency: 1.0 for just-created, decays to 0.0 at max_age_days.
        access_frequency: normalized log of access_count (log(1+count)/log(1+100)).
        explicit_weight: the user-provided importance value (0-1).
        """
        import math

        age_seconds = (datetime.now(tz=timezone.utc) - created_at).total_seconds()
        age_days = max(age_seconds / 86400, 0)
        recency = max(1.0 - (age_days / max_age_days), 0.0)

        access_freq = math.log(1 + access_count) / math.log(1 + 100)
        access_freq = min(access_freq, 1.0)

        score = 0.5 * recency + 0.3 * access_freq + 0.2 * explicit_weight
        return round(min(max(score, 0.0), 1.0), 4)

    async def search(
        self,
        query: str,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
        type_filter: str | None = None,
        top_k: int = 10,
    ) -> list[MemorySearchResult]:
        """Search memories by semantic similarity."""
        embeddings = await self._embedder.embed_texts([query])
        query_embedding = embeddings[0]

        # kNN search in ES
        hits = await self._store.search(
            query_embedding=query_embedding,
            user_id=user_id,
            project_id=project_id,
            type_filter=type_filter,
            top_k=top_k,
        )

        if not hits:
            return []

        # Fetch full memory objects from PG
        memory_ids = [uuid_mod.UUID(h["memory_id"]) for h in hits]
        score_map = {h["memory_id"]: h["score"] for h in hits}

        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id.in_(memory_ids))
            )
            memories = result.scalars().all()

            # Update access counts (importance stays as user-set value;
            # compute_importance() is available for on-read scoring)
            for mem in memories:
                mem.access_count = (mem.access_count or 0) + 1
                mem.last_accessed_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

        # Build scored results, ordered by ES score
        memory_map = {str(m.id): m for m in memories}
        results = []
        for hit in hits:
            mem = memory_map.get(hit["memory_id"])
            if mem:
                results.append(
                    MemorySearchResult(
                        memory=_memory_to_response(mem),
                        score=score_map[hit["memory_id"]],
                    )
                )

        return results

    async def get(self, memory_id: uuid_mod.UUID) -> MemoryResponse | None:
        """Fetch a single memory by ID."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalars().first()
            if memory is None:
                return None
            return _memory_to_response(memory)

    async def list_by_user(
        self,
        user_id: uuid_mod.UUID,
        project_id: uuid_mod.UUID | None = None,
        type_filter: str | None = None,
        limit: int = 50,
    ) -> list[MemoryResponse]:
        """List memories for a user, optionally filtered by project/type."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.updated_at.desc())
            )
            if project_id:
                stmt = stmt.where(Memory.project_id == project_id)
            if type_filter:
                stmt = stmt.where(Memory.type == type_filter)
            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            memories = result.scalars().all()
            return [_memory_to_response(m) for m in memories]

    async def update(
        self,
        memory_id: uuid_mod.UUID,
        content: str | None = None,
        metadata: dict | None = None,
        importance: float | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryResponse | None:
        """Update a memory. Re-embeds and re-indexes if content changes."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalars().first()
            if memory is None:
                return None

            content_changed = False
            if content is not None and content != memory.content:
                memory.content = content
                content_changed = True
            if metadata is not None:
                memory.metadata_ = metadata
            if importance is not None:
                memory.importance = importance
            if expires_at is not None:
                memory.expires_at = expires_at

            memory.updated_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

            # Snapshot values before session closes
            response = _memory_to_response(memory)
            mem_content = memory.content
            mem_user_id = memory.user_id
            mem_project_id = memory.project_id
            mem_type = memory.type
            mem_importance = memory.importance
            mem_source = memory.source

        # ES updates outside session to avoid holding DB connection
        if content_changed:
            embeddings = await self._embedder.embed_texts([mem_content])
            await self._store.index_memory(
                memory_id=memory_id,
                content=mem_content,
                embedding=embeddings[0],
                user_id=mem_user_id,
                project_id=mem_project_id,
                memory_type=mem_type,
                importance=mem_importance,
                source=mem_source,
            )
        elif importance is not None:
            await self._store.update_importance(memory_id, importance)

        return response

    async def delete(self, memory_id: uuid_mod.UUID) -> bool:
        """Delete a memory from PG and ES. Returns True if found and deleted."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalars().first()
            if memory is None:
                return False

            await session.delete(memory)
            await session.flush()
            await session.commit()

        await self._store.delete(memory_id)
        logger.info("memory_deleted", memory_id=str(memory_id))
        return True

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
