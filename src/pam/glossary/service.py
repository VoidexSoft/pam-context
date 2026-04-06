"""Glossary service -- CRUD operations with semantic dedup."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from pam.common.models import GlossaryTerm, GlossaryTermResponse, GlossarySearchResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pam.glossary.store import GlossaryStore
    from pam.ingestion.embedders.base import BaseEmbedder

logger = structlog.get_logger()


def _term_to_response(term: GlossaryTerm) -> GlossaryTermResponse:
    """Convert a GlossaryTerm ORM instance to a GlossaryTermResponse."""
    return GlossaryTermResponse(
        id=term.id,
        project_id=term.project_id,
        canonical=term.canonical,
        aliases=term.aliases if term.aliases else [],
        definition=term.definition,
        category=term.category,
        metadata=term.metadata_ if isinstance(term.metadata_, dict) else {},
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


class GlossaryService:
    """Manages glossary terms with semantic dedup and alias search."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: GlossaryStore,
        embedder: BaseEmbedder,
        dedup_threshold: float = 0.92,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._dedup_threshold = dedup_threshold

    @classmethod
    async def create_from_settings(
        cls,
        session_factory: async_sessionmaker[AsyncSession],
        es_client: object,
        embedder: BaseEmbedder,
        settings: object,
    ) -> GlossaryService:
        """Factory to create GlossaryService + GlossaryStore from app settings."""
        from pam.glossary.store import GlossaryStore

        store = GlossaryStore(
            client=es_client,  # type: ignore[arg-type]
            index_name=settings.glossary_index,  # type: ignore[attr-defined]
            embedding_dims=settings.embedding_dims,  # type: ignore[attr-defined]
        )
        await store.ensure_index()
        return cls(
            session_factory=session_factory,
            store=store,
            embedder=embedder,
            dedup_threshold=settings.glossary_dedup_threshold,  # type: ignore[attr-defined]
        )

    async def add(
        self,
        canonical: str,
        definition: str,
        category: str = "concept",
        aliases: list[str] | None = None,
        metadata: dict | None = None,
        project_id: uuid_mod.UUID | None = None,
    ) -> GlossaryTermResponse:
        """Add a glossary term with semantic deduplication.

        If a term with cosine similarity > threshold exists for the same project,
        raises ValueError with the duplicate's canonical name.
        """
        if not canonical or not canonical.strip():
            raise ValueError("Canonical term cannot be empty")
        if not definition or not definition.strip():
            raise ValueError("Definition cannot be empty")
        canonical = canonical.strip()
        definition = definition.strip()
        aliases = [a.strip() for a in (aliases or []) if a.strip()]

        # Embed the definition for semantic search
        embed_text = f"{canonical}: {definition}"
        embeddings = await self._embedder.embed_texts([embed_text])
        embedding = embeddings[0]

        # Check for duplicates
        duplicates = await self._store.find_duplicates(
            embedding=embedding,
            project_id=project_id,
            threshold=self._dedup_threshold,
        )
        if duplicates:
            dup = duplicates[0]
            raise ValueError(
                f"A similar term already exists: '{dup['canonical']}' "
                f"(similarity: {dup['score']:.2f}). Update the existing term instead."
            )

        # Insert new term
        term_id = uuid_mod.uuid4()
        now = datetime.now(tz=timezone.utc)
        term = GlossaryTerm(
            id=term_id,
            project_id=project_id,
            canonical=canonical,
            aliases=aliases,
            definition=definition,
            category=category,
            metadata_=metadata or {},
            created_at=now,
            updated_at=now,
        )

        async with self._session_factory() as session:
            session.add(term)
            await session.flush()
            await session.commit()

        # Index in ES -- rollback PG if this fails
        try:
            await self._store.index_term(
                term_id=term_id,
                canonical=canonical,
                aliases=aliases,
                definition=definition,
                embedding=embedding,
                category=category,
                project_id=project_id,
            )
        except Exception:
            from sqlalchemy import delete as sa_delete

            async with self._session_factory() as rollback_session:
                await rollback_session.execute(
                    sa_delete(GlossaryTerm).where(GlossaryTerm.id == term_id)
                )
                await rollback_session.commit()
            logger.error("glossary_es_index_failed", term_id=str(term_id), exc_info=True)
            raise

        logger.info("glossary_term_added", term_id=str(term_id), canonical=canonical)
        return _term_to_response(term)

    async def search(
        self,
        query: str,
        project_id: uuid_mod.UUID | None = None,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[GlossarySearchResult]:
        """Search glossary terms by semantic similarity."""
        embeddings = await self._embedder.embed_texts([query])
        query_embedding = embeddings[0]

        hits = await self._store.search(
            query_embedding=query_embedding,
            project_id=project_id,
            category=category,
            top_k=top_k,
        )

        if not hits:
            return []

        # Fetch full term objects from PG
        term_ids = [uuid_mod.UUID(h["term_id"]) for h in hits]
        score_map = {h["term_id"]: h["score"] for h in hits}

        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id.in_(term_ids))
            )
            terms = result.scalars().all()

        term_map = {str(t.id): t for t in terms}
        results = []
        for hit in hits:
            term = term_map.get(hit["term_id"])
            if term:
                results.append(
                    GlossarySearchResult(
                        term=_term_to_response(term),
                        score=score_map[hit["term_id"]],
                    )
                )

        return results

    async def search_by_alias(
        self,
        alias: str,
        project_id: uuid_mod.UUID | None = None,
        top_k: int = 5,
    ) -> list[GlossarySearchResult]:
        """Search glossary terms by keyword match on canonical/aliases."""
        hits = await self._store.search_by_alias(
            alias=alias,
            project_id=project_id,
            top_k=top_k,
        )

        if not hits:
            return []

        term_ids = [uuid_mod.UUID(h["term_id"]) for h in hits]
        score_map = {h["term_id"]: h["score"] for h in hits}

        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id.in_(term_ids))
            )
            terms = result.scalars().all()

        term_map = {str(t.id): t for t in terms}
        results = []
        for hit in hits:
            term = term_map.get(hit["term_id"])
            if term:
                results.append(
                    GlossarySearchResult(
                        term=_term_to_response(term),
                        score=score_map[hit["term_id"]],
                    )
                )

        return results

    async def get(self, term_id: uuid_mod.UUID) -> GlossaryTermResponse | None:
        """Fetch a single term by ID."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id == term_id)
            )
            term = result.scalars().first()
            if term is None:
                return None
            return _term_to_response(term)

    async def list_terms(
        self,
        project_id: uuid_mod.UUID | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GlossaryTermResponse]:
        """List glossary terms, optionally filtered by project/category."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = select(GlossaryTerm).order_by(GlossaryTerm.canonical)
            if project_id:
                stmt = stmt.where(GlossaryTerm.project_id == project_id)
            if category:
                stmt = stmt.where(GlossaryTerm.category == category)
            stmt = stmt.offset(offset).limit(limit)

            result = await session.execute(stmt)
            terms = result.scalars().all()
            return [_term_to_response(t) for t in terms]

    async def update(
        self,
        term_id: uuid_mod.UUID,
        canonical: str | None = None,
        aliases: list[str] | None = None,
        definition: str | None = None,
        category: str | None = None,
        metadata: dict | None = None,
    ) -> GlossaryTermResponse | None:
        """Update a glossary term. Re-embeds and re-indexes if content changes."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id == term_id)
            )
            term = result.scalars().first()
            if term is None:
                return None

            content_changed = False
            if canonical is not None and canonical != term.canonical:
                term.canonical = canonical
                content_changed = True
            if aliases is not None:
                term.aliases = [a.strip() for a in aliases if a.strip()]
                content_changed = True
            if definition is not None and definition != term.definition:
                term.definition = definition
                content_changed = True
            if category is not None:
                term.category = category
            if metadata is not None:
                term.metadata_ = metadata

            term.updated_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

            response = _term_to_response(term)
            t_canonical = term.canonical
            t_aliases = term.aliases or []
            t_definition = term.definition
            t_category = term.category
            t_project_id = term.project_id

        # Re-index in ES if content changed
        if content_changed:
            embed_text = f"{t_canonical}: {t_definition}"
            embeddings = await self._embedder.embed_texts([embed_text])
            await self._store.index_term(
                term_id=term_id,
                canonical=t_canonical,
                aliases=t_aliases,
                definition=t_definition,
                embedding=embeddings[0],
                category=t_category,
                project_id=t_project_id,
            )

        return response

    async def delete(self, term_id: uuid_mod.UUID) -> bool:
        """Delete a glossary term from PG and ES. Returns True if found and deleted."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id == term_id)
            )
            term = result.scalars().first()
            if term is None:
                return False

            await session.delete(term)
            await session.flush()
            await session.commit()

        await self._store.delete(term_id)
        logger.info("glossary_term_deleted", term_id=str(term_id))
        return True
