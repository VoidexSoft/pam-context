"""Data conversion between PAM types and Haystack Document model."""

from __future__ import annotations

import uuid

from haystack import Document

from pam.common.models import KnowledgeSegment
from pam.retrieval.types import SearchResult


def segment_to_haystack_doc(segment: KnowledgeSegment) -> Document:
    """Convert a PAM KnowledgeSegment to a Haystack Document for indexing."""
    return Document(
        id=str(segment.id),
        content=segment.content,
        embedding=segment.embedding,
        meta={
            "segment_id": str(segment.id),
            "document_id": str(segment.document_id) if segment.document_id else None,
            "source_type": segment.source_type,
            "source_id": segment.source_id,
            "source_url": segment.source_url,
            "document_title": segment.document_title,
            "section_path": segment.section_path,
            "segment_type": segment.segment_type,
            "position": segment.position,
        },
    )


def haystack_doc_to_search_result(doc: Document, score: float | None = None) -> SearchResult:
    """Convert a Haystack Document (from retrieval) to a PAM SearchResult."""
    meta = doc.meta or {}
    return SearchResult(
        segment_id=uuid.UUID(meta.get("segment_id", doc.id)),
        content=doc.content or "",
        score=score if score is not None else (doc.score or 0.0),
        source_url=meta.get("source_url"),
        source_id=meta.get("source_id"),
        section_path=meta.get("section_path"),
        document_title=meta.get("document_title"),
        segment_type=meta.get("segment_type", "text"),
    )
