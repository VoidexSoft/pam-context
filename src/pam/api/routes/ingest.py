"""Ingest endpoints — trigger document ingestion and track task progress."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.auth import get_current_user, require_admin
from pam.api.deps import get_db, get_embedder, get_es_client, get_graph_service
from pam.api.pagination import DEFAULT_PAGE_SIZE, PaginatedResponse, decode_cursor, encode_cursor
from pam.common.config import settings
from pam.common.models import (
    IngestionTask,
    IngestionTaskResponse,
    KnowledgeSegment,
    TaskCreatedResponse,
    User,
)
from pam.graph.extraction import extract_graph_for_document, rollback_graph_for_document
from pam.graph.service import GraphitiService
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.ingestion.stores.postgres_store import PostgresStore
from pam.ingestion.task_manager import create_task, get_task, spawn_ingestion_task

logger = structlog.get_logger()

router = APIRouter()


class IngestFolderRequest(BaseModel):
    path: str


@router.post("/ingest/folder", response_model=TaskCreatedResponse, status_code=202)
async def ingest_folder(
    request: Request,
    body: IngestFolderRequest,
    skip_graph: bool = Query(default=False, description="Skip graph extraction"),
    db: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch = Depends(get_es_client),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    _admin: User | None = Depends(require_admin),
):
    """Start background ingestion of all markdown files from a local folder."""
    if not settings.ingest_root:
        raise HTTPException(status_code=400, detail="Ingestion root not configured")

    root = Path(settings.ingest_root).resolve()
    folder = Path(body.path).resolve()
    if not folder.is_relative_to(root):
        raise HTTPException(status_code=403, detail="Path outside allowed ingestion root")

    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {body.path}")

    task = await create_task(body.path, db)
    graph_service = getattr(request.app.state, "graph_service", None)
    spawn_ingestion_task(
        task.id,
        body.path,
        es_client,
        embedder,
        session_factory=request.app.state.session_factory,
        cache_service=request.app.state.cache_service,
        graph_service=graph_service,
        skip_graph=skip_graph,
    )

    return TaskCreatedResponse(task_id=task.id)


@router.get("/ingest/tasks/{task_id}", response_model=IngestionTaskResponse)
async def get_task_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """Get the status of an ingestion task."""
    task = await get_task(task_id, db)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return IngestionTaskResponse.model_validate(task)


@router.get("/ingest/tasks", response_model=PaginatedResponse[IngestionTaskResponse])
async def list_task_statuses(
    cursor: str = "",
    limit: int = Query(default=DEFAULT_PAGE_SIZE, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """List recent ingestion tasks with cursor-based pagination."""
    # Count total
    count_result = await db.execute(select(func.count()).select_from(IngestionTask))
    total = count_result.scalar() or 0

    # Base query
    stmt = select(IngestionTask).order_by(IngestionTask.created_at.desc(), IngestionTask.id.desc())

    # Apply cursor filter for keyset pagination
    if cursor:
        try:
            cursor_data = decode_cursor(cursor)
            cursor_sv = datetime.fromisoformat(cursor_data["sv"])
            cursor_id = uuid.UUID(cursor_data["id"])
            stmt = stmt.where(
                or_(
                    IngestionTask.created_at < cursor_sv,
                    (IngestionTask.created_at == cursor_sv) & (IngestionTask.id < cursor_id),
                )
            )
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    # Fetch limit + 1 to detect next page
    stmt = stmt.limit(limit + 1)
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())

    has_next = len(tasks) > limit
    tasks = tasks[:limit]

    items = [IngestionTaskResponse.model_validate(t) for t in tasks]

    next_cursor = ""
    if has_next and tasks:
        last_task = tasks[-1]
        next_cursor = encode_cursor(
            str(last_task.id),
            last_task.created_at.isoformat() if last_task.created_at else "",
        )

    return PaginatedResponse(items=items, total=total, cursor=next_cursor)


MAX_GRAPH_SYNC_RETRIES = 3


def _segment_to_knowledge_segment(seg) -> KnowledgeSegment:
    """Convert a Segment ORM object to a KnowledgeSegment for graph extraction."""
    return KnowledgeSegment(
        id=seg.id,
        content=seg.content,
        content_hash=seg.content_hash,
        segment_type=seg.segment_type,
        section_path=seg.section_path,
        position=seg.position,
        metadata=seg.metadata_ or {},
        source_type="",
        source_id="",
    )


@router.post("/ingest/sync-graph")
async def sync_graph(
    limit: int | None = Query(default=None, description="Max documents to retry"),
    db: AsyncSession = Depends(get_db),
    graph_service: GraphitiService = Depends(get_graph_service),
    _admin: User | None = Depends(require_admin),
):
    """Retry graph extraction for documents with graph_synced=False.

    Respects a per-document retry limit (MAX_GRAPH_SYNC_RETRIES) and optional
    ``limit`` query param to cap the number of documents processed.
    """
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service not available")

    pg_store = PostgresStore(db)
    unsynced = await pg_store.get_unsynced_documents(
        max_retries=MAX_GRAPH_SYNC_RETRIES, limit=limit
    )

    synced: list[dict] = []
    failed: list[dict] = []

    for doc in unsynced:
        try:
            segments_orm = await pg_store.get_segments_for_document(doc.id)
            segments_ks = [_segment_to_knowledge_segment(seg) for seg in segments_orm]

            result = await extract_graph_for_document(
                graph_service=graph_service,
                doc_id=doc.id,
                segments=segments_ks,
                document_title=doc.title,
                reference_time=doc.last_synced_at or datetime.now(UTC),
                source_id=doc.source_id,
                old_segments=None,  # Sync retry is first-time extraction for failed docs
            )

            await pg_store.set_graph_synced(doc.id, True)
            await pg_store.log_sync(
                doc.id,
                "graph_synced",
                len(result.entities_extracted),
                details=result.diff_summary,
            )
            await db.commit()

            synced.append({
                "doc_id": str(doc.id),
                "status": "synced",
                "entities_added": len(result.entities_extracted),
            })

            logger.info(
                "sync_graph_document_success",
                doc_id=str(doc.id),
                entities=len(result.entities_extracted),
            )

        except Exception as e:
            logger.error(
                "sync_graph_document_failed",
                doc_id=str(doc.id),
                error=str(e),
            )
            await pg_store.set_graph_synced(doc.id, False, increment_retries=True)
            await db.commit()

            # Rollback any partial graph writes
            try:
                segments_orm_rb = await pg_store.get_segments_for_document(doc.id)
                segments_ks_rb = [_segment_to_knowledge_segment(seg) for seg in segments_orm_rb]
                await rollback_graph_for_document(graph_service, segments_ks_rb)
            except Exception:
                logger.error("sync_graph_rollback_failed", doc_id=str(doc.id))

            failed.append({
                "doc_id": str(doc.id),
                "error": str(e),
            })

    # Count remaining unsynced documents
    remaining_docs = await pg_store.get_unsynced_documents(
        max_retries=MAX_GRAPH_SYNC_RETRIES
    )
    remaining = len(remaining_docs)

    return {
        "synced": synced,
        "failed": failed,
        "remaining": remaining,
    }
