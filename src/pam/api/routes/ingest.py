"""Ingest endpoints — trigger document ingestion and track task progress."""

import uuid
from datetime import datetime
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.auth import get_current_user, require_admin
from pam.api.deps import get_db, get_embedder, get_es_client
from pam.api.pagination import DEFAULT_PAGE_SIZE, PaginatedResponse, decode_cursor, encode_cursor
from pam.common.config import settings
from pam.common.models import IngestionTask, IngestionTaskResponse, TaskCreatedResponse, User
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.ingestion.task_manager import create_task, get_task, spawn_ingestion_task

router = APIRouter()


class IngestFolderRequest(BaseModel):
    path: str


@router.post("/ingest/folder", response_model=TaskCreatedResponse, status_code=202)
async def ingest_folder(
    request: Request,
    body: IngestFolderRequest,
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
    spawn_ingestion_task(
        task.id,
        body.path,
        es_client,
        embedder,
        session_factory=request.app.state.session_factory,
        cache_service=request.app.state.cache_service,
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
