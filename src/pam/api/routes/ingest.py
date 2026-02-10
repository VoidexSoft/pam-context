"""Ingest endpoint — trigger document ingestion."""

from pathlib import Path

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.deps import get_db, get_embedder, get_es_client
from pam.ingestion.connectors.markdown import MarkdownConnector
from pam.ingestion.parsers.docling_parser import DoclingParser
from pam.ingestion.pipeline import IngestionPipeline, IngestionResult
from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder

router = APIRouter()


class IngestFolderRequest(BaseModel):
    path: str


class IngestResponse(BaseModel):
    results: list[dict]
    total: int
    succeeded: int
    skipped: int
    failed: int


@router.post("/ingest/folder", response_model=IngestResponse)
async def ingest_folder(
    request: IngestFolderRequest,
    db: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch = Depends(get_es_client),
    embedder: OpenAIEmbedder = Depends(get_embedder),
):
    """Ingest all markdown files from a local folder."""
    folder = Path(request.path)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {request.path}")

    connector = MarkdownConnector(folder)
    parser = DoclingParser()
    es_store = ElasticsearchStore(es_client)

    pipeline = IngestionPipeline(
        connector=connector,
        parser=parser,
        embedder=embedder,
        es_store=es_store,
        session=db,
        source_type="markdown",
    )

    results = await pipeline.ingest_all()

    return IngestResponse(
        results=[
            {
                "source_id": r.source_id,
                "title": r.title,
                "segments_created": r.segments_created,
                "skipped": r.skipped,
                "error": r.error,
            }
            for r in results
        ],
        total=len(results),
        succeeded=sum(1 for r in results if not r.error and not r.skipped),
        skipped=sum(1 for r in results if r.skipped),
        failed=sum(1 for r in results if r.error),
    )
