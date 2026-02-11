"""Ingest endpoints — trigger document ingestion and track task progress."""

import uuid
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.deps import get_db, get_embedder, get_es_client
from pam.common.models import IngestionTaskResponse, TaskCreatedResponse
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.ingestion.task_manager import create_task, get_task, list_tasks, spawn_ingestion_task

router = APIRouter()


class IngestFolderRequest(BaseModel):
    path: str


@router.post("/ingest/folder", response_model=TaskCreatedResponse, status_code=202)
async def ingest_folder(
    request: IngestFolderRequest,
    db: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch = Depends(get_es_client),
    embedder: OpenAIEmbedder = Depends(get_embedder),
):
    """Start background ingestion of all markdown files from a local folder."""
    folder = Path(request.path)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {request.path}")

    task = await create_task(request.path, db)
    spawn_ingestion_task(task.id, request.path, es_client, embedder)

    return TaskCreatedResponse(task_id=task.id)


@router.get("/ingest/tasks/{task_id}", response_model=IngestionTaskResponse)
async def get_task_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the status of an ingestion task."""
    task = await get_task(task_id, db)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return IngestionTaskResponse.model_validate(task)


@router.get("/ingest/tasks", response_model=list[IngestionTaskResponse])
async def list_task_statuses(
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List recent ingestion tasks."""
    tasks = await list_tasks(db, limit=limit)
    return [IngestionTaskResponse.model_validate(t) for t in tasks]
