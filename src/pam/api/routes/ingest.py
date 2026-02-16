"""Ingest endpoints — trigger document ingestion and track task progress."""

import uuid
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.auth import get_current_user, require_admin
from pam.api.deps import get_db, get_embedder, get_es_client
from pam.api.pagination import PaginatedResponse
from pam.common.config import settings
from pam.common.models import IngestionTaskResponse, TaskCreatedResponse, User
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.ingestion.task_manager import create_task, get_task, list_tasks, spawn_ingestion_task

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
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User | None = Depends(get_current_user),
):
    """List recent ingestion tasks with cursor-based pagination."""
    tasks = await list_tasks(db, limit=limit)
    items = [IngestionTaskResponse.model_validate(t) for t in tasks]
    return PaginatedResponse(items=items, total=len(items), cursor="")
