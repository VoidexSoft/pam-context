"""Background ingestion task lifecycle management.

Uses PostgreSQL to track task state and asyncio.create_task() for background execution.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from elasticsearch import AsyncElasticsearch
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.cache import CacheService, get_redis
from pam.common.config import settings
from pam.common.database import async_session_factory
from pam.common.models import IngestionTask
from pam.ingestion.connectors.markdown import MarkdownConnector
from pam.ingestion.embedders.base import BaseEmbedder
from pam.ingestion.parsers.docling_parser import DoclingParser
from pam.ingestion.pipeline import IngestionPipeline, IngestionResult
from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore

logger = structlog.get_logger()

# Registry of running asyncio tasks
_running_tasks: dict[uuid.UUID, asyncio.Task] = {}


async def create_task(folder_path: str, session: AsyncSession) -> IngestionTask:
    """Create a pending ingestion task record in the database."""
    task = IngestionTask(folder_path=folder_path)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(task_id: uuid.UUID, session: AsyncSession) -> IngestionTask | None:
    """Fetch an ingestion task by ID."""
    result = await session.execute(select(IngestionTask).where(IngestionTask.id == task_id))
    return result.scalar_one_or_none()


async def list_tasks(session: AsyncSession, limit: int = 20) -> list[IngestionTask]:
    """List recent ingestion tasks, newest first."""
    result = await session.execute(
        select(IngestionTask).order_by(IngestionTask.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def spawn_ingestion_task(
    task_id: uuid.UUID,
    folder_path: str,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
) -> None:
    """Spawn a background asyncio task for ingestion."""
    asyncio_task = asyncio.create_task(
        run_ingestion_background(task_id, folder_path, es_client, embedder),
        name=f"ingest-{task_id}",
    )
    _running_tasks[task_id] = asyncio_task
    logger.info("task_spawned", task_id=str(task_id), folder_path=folder_path)


async def run_ingestion_background(
    task_id: uuid.UUID,
    folder_path: str,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
) -> None:
    """Background coroutine that runs the ingestion pipeline and updates task state."""
    try:
        # Use a dedicated session for task status updates
        async with async_session_factory() as status_session:
            # Mark task as running
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await status_session.commit()

            # Count documents
            connector = MarkdownConnector(folder_path)
            docs = await connector.list_documents()
            total = len(docs)

            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(total_documents=total)
            )
            await status_session.commit()

            if total == 0:
                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="completed", completed_at=datetime.now(UTC))
                )
                await status_session.commit()
                return

            # Progress callback — updates task record after each document
            async def on_progress(result: IngestionResult) -> None:
                task_row = await get_task(task_id, status_session)
                if task_row is None:
                    return
                new_processed = task_row.processed_documents + 1
                new_succeeded = task_row.succeeded + (1 if not result.error and not result.skipped else 0)
                new_skipped = task_row.skipped + (1 if result.skipped else 0)
                new_failed = task_row.failed + (1 if result.error else 0)
                new_results = list(task_row.results) + [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                    }
                ]
                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=new_processed,
                        succeeded=new_succeeded,
                        skipped=new_skipped,
                        failed=new_failed,
                        results=new_results,
                    )
                )
                await status_session.commit()

            # Run the pipeline with a separate DB session
            async with async_session_factory() as pipeline_session:
                # Create parser based on config
                if settings.parser == "mineru":
                    from pam.ingestion.parsers.mineru_parser import MineruParser
                    parser = MineruParser()
                else:
                    parser = DoclingParser()
                es_store = ElasticsearchStore(es_client)

                # Create multimodal processor if enabled
                multimodal_processor = None
                if settings.enable_multimodal:
                    from pam.common.llm.factory import create_llm_client
                    from pam.ingestion.processors.multimodal import (
                        MultimodalConfig,
                        MultimodalProcessor,
                    )

                    llm_client = create_llm_client()
                    multimodal_processor = MultimodalProcessor(
                        llm_client=llm_client,
                        config=MultimodalConfig(
                            enable_image_processing=settings.enable_image_processing,
                            enable_table_processing=settings.enable_table_processing,
                            context_window_chars=settings.multimodal_context_chars,
                        ),
                    )

                pipeline = IngestionPipeline(
                    connector=connector,
                    parser=parser,
                    embedder=embedder,
                    es_store=es_store,
                    session=pipeline_session,
                    source_type="markdown",
                    progress_callback=on_progress,
                    multimodal_processor=multimodal_processor,
                )
                await pipeline.ingest_all()

            # Mark completed
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await status_session.commit()

            # Invalidate search cache after successful ingestion
            try:
                redis_client = await get_redis()
                cache = CacheService(redis_client)
                cleared = await cache.invalidate_search()
                logger.info("cache_invalidated_after_ingest", keys_cleared=cleared)
            except Exception:
                logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("task_completed", task_id=str(task_id))

    except Exception as e:
        logger.exception("task_failed", task_id=str(task_id))
        try:
            async with async_session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        status="failed",
                        error=str(e),
                        completed_at=datetime.now(UTC),
                    )
                )
                await err_session.commit()
        except Exception:
            logger.exception("task_failed_status_update_error", task_id=str(task_id))

    finally:
        _running_tasks.pop(task_id, None)
