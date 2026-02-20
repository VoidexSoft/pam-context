"""Ingestion pipeline orchestrator: connector → parser → chunker → embedder → stores."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.config import settings
from pam.common.models import KnowledgeSegment, Segment
from pam.graph.extraction import (
    ExtractionResult,
    extract_graph_for_document,
    rollback_graph_for_document,
)
from pam.ingestion.chunkers.hybrid_chunker import chunk_document
from pam.ingestion.connectors.base import BaseConnector
from pam.ingestion.embedders.base import BaseEmbedder
from pam.ingestion.parsers.docling_parser import DoclingParser
from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore
from pam.ingestion.stores.postgres_store import PostgresStore

if TYPE_CHECKING:
    from pam.graph.service import GraphitiService

logger = structlog.get_logger()


@dataclass
class IngestionResult:
    source_id: str
    title: str
    segments_created: int
    skipped: bool = False
    error: str | None = None
    graph_synced: bool = False
    graph_entities_extracted: int = 0
    diff_summary: dict | None = None


@dataclass
class IngestionPipeline:
    connector: BaseConnector
    parser: DoclingParser
    embedder: BaseEmbedder
    es_store: ElasticsearchStore
    session: AsyncSession
    source_type: str = "markdown"
    progress_callback: Callable[[IngestionResult], Awaitable[None]] | None = None
    graph_service: GraphitiService | None = None
    skip_graph: bool = False

    async def ingest_document(self, source_id: str) -> IngestionResult:
        """Ingest a single document through the full pipeline.

        1. Fetch raw document
        2. Check content hash — skip if unchanged
        3. Parse with Docling
        4. Chunk with HybridChunker
        5. Embed all chunks (batched)
        6. Write to PostgreSQL (document + segments)
        7. Write to Elasticsearch (segments + embeddings)
        8. Log to sync_log
        """
        pg_store = PostgresStore(self.session)

        try:
            # 1. Fetch raw document
            raw_doc = await self.connector.fetch_document(source_id)
            logger.info("pipeline_fetch", source_id=source_id, title=raw_doc.title)

            # 2. Content hash check — computed from already-fetched content to avoid double-fetch
            new_hash = hashlib.sha256(raw_doc.content).hexdigest()
            existing_doc = await pg_store.get_document_by_source(self.source_type, source_id)

            if existing_doc and existing_doc.content_hash == new_hash:
                logger.info("pipeline_skip_unchanged", source_id=source_id)
                return IngestionResult(source_id=source_id, title=raw_doc.title, segments_created=0, skipped=True)

            # 3. Parse with Docling
            docling_doc = self.parser.parse(raw_doc)

            # 4. Chunk
            chunks = chunk_document(docling_doc, max_tokens=settings.chunk_size_tokens)
            if not chunks:
                logger.warning("pipeline_no_chunks", source_id=source_id)
                return IngestionResult(source_id=source_id, title=raw_doc.title, segments_created=0)

            # 5. Embed
            texts = [c.content for c in chunks]
            hashes = [c.content_hash for c in chunks]
            embeddings = await self.embedder.embed_texts_with_cache(texts, hashes)

            # 6. Build KnowledgeSegment objects
            segments = [
                KnowledgeSegment(
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    embedding=embedding,
                    source_type=self.source_type,
                    source_id=source_id,
                    source_url=raw_doc.source_url,
                    section_path=chunk.section_path,
                    segment_type=chunk.segment_type,
                    position=chunk.position,
                    document_title=raw_doc.title,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]

            # 6b. Retrieve old segments for diff BEFORE save_segments deletes them
            old_segments_for_diff = None
            if existing_doc:
                old_segments_raw = await pg_store.get_segments_for_document(existing_doc.id)
                old_segments_for_diff = old_segments_raw if old_segments_raw else None

            # 7. Write to PostgreSQL
            doc_id = await pg_store.upsert_document(
                source_type=self.source_type,
                source_id=source_id,
                title=raw_doc.title,
                content_hash=new_hash,
                source_url=raw_doc.source_url,
                owner=raw_doc.owner,
            )

            # Set document_id on all segments
            for seg in segments:
                seg.document_id = doc_id

            count = await pg_store.save_segments(doc_id, segments)

            # 8. Log sync
            action = "updated" if existing_doc else "created"
            await pg_store.log_sync(doc_id, action, count)

            # 9. Commit PG first — PG is authoritative
            await self.session.commit()

            # 10. Write to Elasticsearch (delete old, index new)
            # If ES fails after PG commit, log error but don't fail — ES catches up on re-ingestion
            try:
                await self.es_store.delete_by_document(doc_id)
                await self.es_store.bulk_index(segments)
            except Exception as es_err:
                logger.error(
                    "pipeline_es_write_failed",
                    source_id=source_id,
                    doc_id=str(doc_id),
                    error=str(es_err),
                )

            # 11. Graph extraction (non-blocking -- failure never rolls back PG/ES)
            graph_synced = False
            diff_summary = None
            graph_entities_count = 0
            if self.graph_service and not self.skip_graph:
                try:
                    extraction_result: ExtractionResult = await extract_graph_for_document(
                        graph_service=self.graph_service,
                        doc_id=doc_id,
                        segments=segments,
                        document_title=raw_doc.title,
                        reference_time=getattr(raw_doc, "modified_at", None) or datetime.now(UTC),
                        source_id=source_id,
                        old_segments=old_segments_for_diff,
                    )
                    graph_synced = True
                    diff_summary = extraction_result.diff_summary
                    graph_entities_count = len(extraction_result.entities_extracted)
                    await pg_store.set_graph_synced(doc_id, True)

                    # Update segment metadata with episode UUIDs (save back to PG)
                    for seg in segments:
                        if seg.metadata.get("graph_episode_uuid"):
                            await self.session.execute(
                                sa_update(Segment)
                                .where(Segment.id == seg.id)
                                .values(metadata_=seg.metadata)
                            )
                    await self.session.commit()

                    # Log graph sync event with diff summary
                    await pg_store.log_sync(
                        doc_id, "graph_synced", graph_entities_count, details=diff_summary or {}
                    )
                    await self.session.commit()

                    logger.info(
                        "pipeline_graph_extraction_complete",
                        source_id=source_id,
                        entities=graph_entities_count,
                        episodes_added=extraction_result.episodes_added,
                    )
                except Exception as graph_err:
                    logger.error(
                        "pipeline_graph_extraction_failed",
                        source_id=source_id,
                        doc_id=str(doc_id),
                        error=str(graph_err),
                    )
                    await pg_store.set_graph_synced(doc_id, False)
                    await self.session.commit()
                    # Rollback any partial graph writes for this document
                    try:
                        rolled_back = await rollback_graph_for_document(self.graph_service, segments)
                        logger.info(
                            "pipeline_graph_rollback",
                            source_id=source_id,
                            episodes_rolled_back=rolled_back,
                        )
                    except Exception:
                        logger.error("pipeline_graph_rollback_failed", source_id=source_id)

            logger.info("pipeline_complete", source_id=source_id, title=raw_doc.title, segments=count, action=action)
            return IngestionResult(
                source_id=source_id,
                title=raw_doc.title,
                segments_created=count,
                graph_synced=graph_synced,
                graph_entities_extracted=graph_entities_count,
                diff_summary=diff_summary,
            )

        except Exception as e:
            await self.session.rollback()
            logger.exception("pipeline_error", source_id=source_id)
            return IngestionResult(source_id=source_id, title=source_id, segments_created=0, error=str(e))

    async def ingest_all(self) -> list[IngestionResult]:
        """List all documents from connector and ingest each."""
        docs = await self.connector.list_documents()
        logger.info("pipeline_ingest_all", total_documents=len(docs))

        results = []
        for doc_info in docs:
            result = await self.ingest_document(doc_info.source_id)
            results.append(result)
            if self.progress_callback:
                await self.progress_callback(result)

        succeeded = sum(1 for r in results if not r.error and not r.skipped)
        skipped = sum(1 for r in results if r.skipped)
        failed = sum(1 for r in results if r.error)
        logger.info("pipeline_ingest_all_complete", succeeded=succeeded, skipped=skipped, failed=failed)

        return results
