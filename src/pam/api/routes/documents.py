"""Documents endpoint — list and view ingested documents."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.auth import get_current_user
from pam.api.deps import get_db
from pam.common.models import Document, ExtractedEntity, IngestionTask, Segment, User
from pam.ingestion.stores.postgres_store import PostgresStore

router = APIRouter()


@router.get("/documents")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """List all ingested documents with segment counts."""
    store = PostgresStore(db)
    return await store.list_documents()


@router.get("/segments/{segment_id}")
async def get_segment(
    segment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """Get segment content and metadata for the source viewer."""
    result = await db.execute(select(Segment).where(Segment.id == segment_id))
    segment = result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Get parent document for title and source URL
    doc_result = await db.execute(select(Document).where(Document.id == segment.document_id))
    doc = doc_result.scalar_one_or_none()

    return {
        "id": str(segment.id),
        "content": segment.content,
        "segment_type": segment.segment_type,
        "section_path": segment.section_path,
        "position": segment.position,
        "metadata": segment.metadata_,
        "document_id": str(segment.document_id),
        "document_title": doc.title if doc else None,
        "source_url": doc.source_url if doc else None,
        "source_type": doc.source_type if doc else None,
    }


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """Get system stats for admin dashboard."""
    # Document counts by status
    doc_result = await db.execute(select(Document.status, func.count()).group_by(Document.status))
    doc_counts = {row[0]: row[1] for row in doc_result.all()}

    # Total segments
    seg_result = await db.execute(select(func.count()).select_from(Segment))
    segment_count = seg_result.scalar() or 0

    # Entity counts by type
    try:
        entity_result = await db.execute(
            select(ExtractedEntity.entity_type, func.count()).group_by(ExtractedEntity.entity_type)
        )
        entity_counts = {row[0]: row[1] for row in entity_result.all()}
    except Exception:
        entity_counts = {}

    # Recent ingestion tasks
    task_result = await db.execute(select(IngestionTask).order_by(IngestionTask.created_at.desc()).limit(10))
    recent_tasks = task_result.scalars().all()

    return {
        "documents": {
            "total": sum(doc_counts.values()),
            "by_status": doc_counts,
        },
        "segments": segment_count,
        "entities": {
            "total": sum(entity_counts.values()),
            "by_type": entity_counts,
        },
        "recent_tasks": [
            {
                "id": str(t.id),
                "status": t.status,
                "folder_path": t.folder_path,
                "total_documents": t.total_documents,
                "succeeded": t.succeeded,
                "failed": t.failed,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in recent_tasks
        ],
    }
