"""Background ingestion task lifecycle management.

Uses PostgreSQL to track task state and asyncio.create_task() for background execution.
"""

from __future__ import annotations

import asyncio
import json as json_module
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from elasticsearch import AsyncElasticsearch
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.expression import cast, literal

from pam.common.cache import CacheService
from pam.common.config import settings
from pam.common.models import IngestionTask
from pam.ingestion.connectors.github import GitHubConnector
from pam.ingestion.connectors.markdown import MarkdownConnector
from pam.ingestion.embedders.base import BaseEmbedder
from pam.ingestion.parsers.docling_parser import DoclingParser
from pam.ingestion.pipeline import IngestionPipeline, IngestionResult
from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore

if TYPE_CHECKING:
    from pam.graph.service import GraphitiService
    from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore

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
    task: IngestionTask | None = result.scalar_one_or_none()
    return task


async def list_tasks(session: AsyncSession, limit: int = 20) -> list[IngestionTask]:
    """List recent ingestion tasks, newest first."""
    result = await session.execute(select(IngestionTask).order_by(IngestionTask.created_at.desc()).limit(limit))
    return list(result.scalars().all())


def spawn_ingestion_task(
    task_id: uuid.UUID,
    folder_path: str,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Spawn a background asyncio task for ingestion."""
    asyncio_task = asyncio.create_task(
        run_ingestion_background(
            task_id, folder_path, es_client, embedder, session_factory,
            cache_service, graph_service, skip_graph, vdb_store,
        ),
        name=f"ingest-{task_id}",
    )
    _running_tasks[task_id] = asyncio_task
    logger.info("task_spawned", task_id=str(task_id), folder_path=folder_path)


async def run_ingestion_background(
    task_id: uuid.UUID,
    folder_path: str,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Background coroutine that runs the ingestion pipeline and updates task state."""
    try:
        # Use a dedicated session for task status updates
        async with session_factory() as status_session:
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
                update(IngestionTask).where(IngestionTask.id == task_id).values(total_documents=total)
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
            # Uses SQL-level increments for atomicity (no read-modify-write race)
            async def on_progress(result: IngestionResult) -> None:
                result_entry = [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                        "graph_synced": result.graph_synced,
                        "graph_entities_extracted": result.graph_entities_extracted,
                    }
                ]
                succeeded_inc = 1 if not result.error and not result.skipped else 0
                skipped_inc = 1 if result.skipped else 0
                failed_inc = 1 if result.error else 0

                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=IngestionTask.processed_documents + 1,
                        succeeded=IngestionTask.succeeded + succeeded_inc,
                        skipped=IngestionTask.skipped + skipped_inc,
                        failed=IngestionTask.failed + failed_inc,
                        results=IngestionTask.results
                        + cast(
                            literal(json_module.dumps(result_entry)),
                            JSONB,
                        ),
                    )
                )
                await status_session.commit()

            # Run the pipeline with a separate DB session
            async with session_factory() as pipeline_session:
                parser = DoclingParser()
                es_store = ElasticsearchStore(
                    es_client,
                    index_name=settings.elasticsearch_index,
                    embedding_dims=settings.embedding_dims,
                )
                pipeline = IngestionPipeline(
                    connector=connector,
                    parser=parser,
                    embedder=embedder,
                    es_store=es_store,
                    session=pipeline_session,
                    source_type="markdown",
                    progress_callback=on_progress,
                    graph_service=graph_service,
                    vdb_store=vdb_store,
                    skip_graph=skip_graph,
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
            if cache_service:
                try:
                    cleared = await cache_service.invalidate_search()
                    logger.info("cache_invalidated_after_ingest", keys_cleared=cleared)
                except Exception:
                    logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("task_completed", task_id=str(task_id))

    except asyncio.CancelledError:
        logger.warning("task_cancelled", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        status="failed",
                        error="Task was cancelled",
                        completed_at=datetime.now(UTC),
                    )
                )
                await err_session.commit()
        except Exception:
            logger.exception("task_cancelled_status_update_error", task_id=str(task_id))

    except Exception as e:
        logger.exception("task_failed", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
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


def spawn_github_ingestion_task(
    task_id: uuid.UUID,
    repo_config: dict,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Spawn a background asyncio task for GitHub ingestion."""
    asyncio_task = asyncio.create_task(
        run_github_ingestion_background(
            task_id, repo_config, es_client, embedder, session_factory,
            cache_service, graph_service, skip_graph, vdb_store,
        ),
        name=f"ingest-github-{task_id}",
    )
    _running_tasks[task_id] = asyncio_task
    logger.info("github_task_spawned", task_id=str(task_id), repo=repo_config.get("repo"))


async def run_github_ingestion_background(
    task_id: uuid.UUID,
    repo_config: dict,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Background coroutine for GitHub repo ingestion."""
    try:
        async with session_factory() as status_session:
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await status_session.commit()

            connector = GitHubConnector(
                repo=repo_config["repo"],
                branch=repo_config.get("branch", "main"),
                paths=repo_config.get("paths", []),
                extensions=repo_config.get("extensions", [".md", ".txt"]),
            )
            docs = await connector.list_documents()
            total = len(docs)

            await status_session.execute(
                update(IngestionTask).where(IngestionTask.id == task_id).values(total_documents=total)
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

            async def on_progress(result: IngestionResult) -> None:
                result_entry = [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                        "graph_synced": result.graph_synced,
                        "graph_entities_extracted": result.graph_entities_extracted,
                    }
                ]
                succeeded_inc = 1 if not result.error and not result.skipped else 0
                skipped_inc = 1 if result.skipped else 0
                failed_inc = 1 if result.error else 0

                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=IngestionTask.processed_documents + 1,
                        succeeded=IngestionTask.succeeded + succeeded_inc,
                        skipped=IngestionTask.skipped + skipped_inc,
                        failed=IngestionTask.failed + failed_inc,
                        results=IngestionTask.results
                        + cast(literal(json_module.dumps(result_entry)), JSONB),
                    )
                )
                await status_session.commit()

            async with session_factory() as pipeline_session:
                parser = DoclingParser()
                es_store = ElasticsearchStore(
                    es_client,
                    index_name=settings.elasticsearch_index,
                    embedding_dims=settings.embedding_dims,
                )
                pipeline = IngestionPipeline(
                    connector=connector,
                    parser=parser,
                    embedder=embedder,
                    es_store=es_store,
                    session=pipeline_session,
                    source_type="github",
                    progress_callback=on_progress,
                    graph_service=graph_service,
                    vdb_store=vdb_store,
                    skip_graph=skip_graph,
                )
                await pipeline.ingest_all()

            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await status_session.commit()

            if cache_service:
                try:
                    cleared = await cache_service.invalidate_search()
                    logger.info("cache_invalidated_after_github_ingest", keys_cleared=cleared)
                except Exception:
                    logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("github_task_completed", task_id=str(task_id))

    except Exception as e:
        logger.exception("github_task_failed", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="failed", error=str(e), completed_at=datetime.now(UTC))
                )
                await err_session.commit()
        except Exception:
            logger.exception("github_task_failed_status_update_error", task_id=str(task_id))
    finally:
        _running_tasks.pop(task_id, None)


def spawn_sync_task(
    task_id: uuid.UUID,
    sources: list[str],
    github_repos: list[dict],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Spawn a background asyncio task for multi-source sync."""
    asyncio_task = asyncio.create_task(
        run_sync_background(
            task_id, sources, github_repos, es_client, embedder, session_factory,
            cache_service, graph_service, skip_graph, vdb_store,
        ),
        name=f"ingest-sync-{task_id}",
    )
    _running_tasks[task_id] = asyncio_task
    logger.info("sync_task_spawned", task_id=str(task_id), sources=sources)


async def run_sync_background(
    task_id: uuid.UUID,
    sources: list[str],
    github_repos: list[dict],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Background coroutine for multi-source sync."""
    try:
        async with session_factory() as status_session:
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await status_session.commit()

            all_results: list[IngestionResult] = []
            total_docs = 0

            async def on_progress(result: IngestionResult) -> None:
                result_entry = [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                    }
                ]
                succeeded_inc = 1 if not result.error and not result.skipped else 0
                skipped_inc = 1 if result.skipped else 0
                failed_inc = 1 if result.error else 0

                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=IngestionTask.processed_documents + 1,
                        succeeded=IngestionTask.succeeded + succeeded_inc,
                        skipped=IngestionTask.skipped + skipped_inc,
                        failed=IngestionTask.failed + failed_inc,
                        results=IngestionTask.results
                        + cast(literal(json_module.dumps(result_entry)), JSONB),
                    )
                )
                await status_session.commit()

            # GitHub sources
            if "github" in sources:
                for repo_config in github_repos:
                    connector = GitHubConnector(
                        repo=repo_config["repo"],
                        branch=repo_config.get("branch", "main"),
                        paths=repo_config.get("paths", []),
                        extensions=repo_config.get("extensions", [".md", ".txt"]),
                    )
                    docs = await connector.list_documents()
                    total_docs += len(docs)

                    await status_session.execute(
                        update(IngestionTask)
                        .where(IngestionTask.id == task_id)
                        .values(total_documents=total_docs)
                    )
                    await status_session.commit()

                    async with session_factory() as pipeline_session:
                        parser = DoclingParser()
                        es_store = ElasticsearchStore(
                            es_client,
                            index_name=settings.elasticsearch_index,
                            embedding_dims=settings.embedding_dims,
                        )
                        pipeline = IngestionPipeline(
                            connector=connector,
                            parser=parser,
                            embedder=embedder,
                            es_store=es_store,
                            session=pipeline_session,
                            source_type="github",
                            progress_callback=on_progress,
                            graph_service=graph_service,
                            vdb_store=vdb_store,
                            skip_graph=skip_graph,
                        )
                        results = await pipeline.ingest_all()
                        all_results.extend(results)

            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await status_session.commit()

            if cache_service:
                try:
                    cleared = await cache_service.invalidate_search()
                    logger.info("cache_invalidated_after_sync", keys_cleared=cleared)
                except Exception:
                    logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("sync_task_completed", task_id=str(task_id), total_results=len(all_results))

    except Exception as e:
        logger.exception("sync_task_failed", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="failed", error=str(e), completed_at=datetime.now(UTC))
                )
                await err_session.commit()
        except Exception:
            logger.exception("sync_task_failed_status_update_error", task_id=str(task_id))
    finally:
        _running_tasks.pop(task_id, None)


async def recover_stale_tasks(session_factory: async_sessionmaker) -> int:
    """Mark any 'running' tasks as 'failed' on startup.

    Tasks stuck in 'running' state indicate a previous crash or unclean shutdown.
    This should be called once during application startup.
    """
    async with session_factory() as session:
        result = await session.execute(
            update(IngestionTask)
            .where(IngestionTask.status == "running")
            .values(
                status="failed",
                error="Recovered on startup: task was stuck in running state",
                completed_at=datetime.now(UTC),
            )
        )
        await session.commit()
        count: int = result.rowcount  # type: ignore[attr-defined]
        if count:
            logger.warning("recovered_stale_tasks", count=count)
        return count
