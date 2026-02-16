"""Documents endpoint — list and view ingested documents."""

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pam.api.auth import get_current_user
from pam.api.deps import get_db
from pam.api.pagination import DEFAULT_PAGE_SIZE, PaginatedResponse, decode_cursor, encode_cursor
from pam.common.models import (
    Document,
    DocumentResponse,
    ExtractedEntity,
    IngestionTask,
    Segment,
    SegmentDetailResponse,
    StatsResponse,
    User,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/documents", response_model=PaginatedResponse[DocumentResponse])
async def list_documents(
    cursor: str = "",
    limit: int = Query(default=DEFAULT_PAGE_SIZE, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """List all ingested documents with segment counts and cursor-based pagination."""
    # Count total
    count_result = await db.execute(select(func.count()).select_from(Document))
    total = count_result.scalar() or 0

    # Base query with segment counts
    stmt = (
        select(
            Document,
            func.count(Segment.id).label("segment_count"),
        )
        .outerjoin(Segment)
        .group_by(Document.id)
        .order_by(Document.updated_at.desc(), Document.id.desc())
    )

    # Apply cursor filter for keyset pagination
    if cursor:
        try:
            cursor_data = decode_cursor(cursor)
            cursor_sv = datetime.fromisoformat(cursor_data["sv"])
            cursor_id = uuid.UUID(cursor_data["id"])
            stmt = stmt.where(
                or_(
                    Document.updated_at < cursor_sv,
                    (Document.updated_at == cursor_sv) & (Document.id < cursor_id),
                )
            )
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    # Fetch limit + 1 to detect next page
    stmt = stmt.limit(limit + 1)
    result = await db.execute(stmt)
    rows = result.all()

    has_next = len(rows) > limit
    rows = rows[:limit]

    items = [
        DocumentResponse(
            id=doc.id,
            source_type=doc.source_type,
            source_id=doc.source_id,
            source_url=doc.source_url,
            title=doc.title,
            owner=doc.owner,
            status=doc.status,
            content_hash=doc.content_hash,
            last_synced_at=doc.last_synced_at,
            created_at=doc.created_at,
            segment_count=count,
        )
        for doc, count in rows
    ]

    next_cursor = ""
    if has_next and rows:
        last_doc = rows[-1][0]
        next_cursor = encode_cursor(
            str(last_doc.id),
            last_doc.updated_at.isoformat() if last_doc.updated_at else "",
        )

    return PaginatedResponse(items=items, total=total, cursor=next_cursor)


@router.get("/segments/{segment_id}", response_model=SegmentDetailResponse)
async def get_segment(
    segment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """Get segment content and metadata for the source viewer."""
    result = await db.execute(
        select(Segment)
        .options(selectinload(Segment.document))
        .where(Segment.id == segment_id)
    )
    segment = result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    doc = segment.document
    return SegmentDetailResponse(
        id=segment.id,
        content=segment.content,
        segment_type=segment.segment_type,
        section_path=segment.section_path,
        position=segment.position,
        metadata=segment.metadata_,
        document_id=segment.document_id,
        document_title=doc.title if doc else None,
        source_url=doc.source_url if doc else None,
        source_type=doc.source_type if doc else None,
    )


@router.get("/stats", response_model=StatsResponse)
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
        logger.warning("entity_count_query_failed", exc_info=True)
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
