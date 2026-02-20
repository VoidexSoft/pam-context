"""PostgreSQL storage for documents, segments, and sync log."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.models import Document, KnowledgeSegment, Segment, SyncLog

logger = structlog.get_logger()


class PostgresStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_document(
        self,
        source_type: str,
        source_id: str,
        title: str,
        content_hash: str,
        source_url: str | None = None,
        owner: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Insert or update a document record. Returns the document ID."""
        stmt = insert(Document).values(
            source_type=source_type,
            source_id=source_id,
            title=title,
            content_hash=content_hash,
            source_url=source_url,
            owner=owner,
            project_id=project_id,
            last_synced_at=datetime.now(UTC),
        )
        stmt = stmt.on_conflict_on_constraint("uq_documents_source").do_update(  # type: ignore[attr-defined]
            set_={
                "title": stmt.excluded.title,
                "content_hash": stmt.excluded.content_hash,
                "source_url": stmt.excluded.source_url,
                "owner": stmt.excluded.owner,
                "last_synced_at": stmt.excluded.last_synced_at,
                "updated_at": func.now(),
            }
        )
        stmt = stmt.returning(Document.id)
        result = await self.session.execute(stmt)
        doc_id: uuid.UUID = result.scalar_one()
        await self.session.flush()

        logger.info("upsert_document", document_id=str(doc_id), source_type=source_type, source_id=source_id)
        return doc_id

    async def save_segments(self, document_id: uuid.UUID, segments: list[KnowledgeSegment]) -> int:
        """Replace all segments for a document (delete old, insert new)."""
        # Delete existing segments
        await self.session.execute(delete(Segment).where(Segment.document_id == document_id))

        # Insert new segments
        for seg in segments:
            db_seg = Segment(
                id=seg.id,
                document_id=document_id,
                content=seg.content,
                content_hash=seg.content_hash,
                segment_type=seg.segment_type,
                section_path=seg.section_path,
                position=seg.position,
                metadata_=seg.metadata,
            )
            self.session.add(db_seg)

        await self.session.flush()
        logger.info("save_segments", document_id=str(document_id), count=len(segments))
        return len(segments)

    async def log_sync(
        self,
        document_id: uuid.UUID,
        action: str,
        segments_affected: int,
        details: dict | None = None,
    ) -> None:
        log_entry = SyncLog(
            document_id=document_id,
            action=action,
            segments_affected=segments_affected,
            details=details or {},
        )
        self.session.add(log_entry)
        await self.session.flush()

    async def get_document_by_source(self, source_type: str, source_id: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.source_type == source_type, Document.source_id == source_id)
        )
        doc: Document | None = result.scalar_one_or_none()
        return doc

    async def list_documents(self) -> list[dict]:
        """List all documents with segment counts."""
        stmt = (
            select(
                Document,
                func.count(Segment.id).label("segment_count"),
            )
            .outerjoin(Segment)
            .group_by(Document.id)
            .order_by(Document.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": doc.id,
                "source_type": doc.source_type,
                "source_id": doc.source_id,
                "source_url": doc.source_url,
                "title": doc.title,
                "owner": doc.owner,
                "status": doc.status,
                "content_hash": doc.content_hash,
                "last_synced_at": doc.last_synced_at,
                "created_at": doc.created_at,
                "segment_count": count,
            }
            for doc, count in rows
        ]

    async def set_graph_synced(
        self, document_id: uuid.UUID, synced: bool, increment_retries: bool = False
    ) -> None:
        """Update graph_synced flag for a document.

        If synced=True, resets graph_sync_retries to 0.
        If increment_retries=True, increments graph_sync_retries by 1.
        """
        values: dict = {"graph_synced": synced}
        if synced:
            values["graph_sync_retries"] = 0
        elif increment_retries:
            values["graph_sync_retries"] = Document.graph_sync_retries + 1

        stmt = update(Document).where(Document.id == document_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_unsynced_documents(
        self, max_retries: int = 3, limit: int | None = None
    ) -> list[Document]:
        """Get documents that need graph sync (not synced and under retry limit)."""
        stmt = select(Document).where(
            Document.graph_synced == False,  # noqa: E712
            Document.graph_sync_retries < max_retries,
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_segments_for_document(self, document_id: uuid.UUID) -> list[Segment]:
        """Get all segments for a document, ordered by position."""
        stmt = (
            select(Segment)
            .where(Segment.document_id == document_id)
            .order_by(Segment.position)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
