"""Chunking using Docling's HybridChunker with configurable token size."""

import hashlib
from dataclasses import dataclass

import structlog
from docling_core.types.doc import DoclingDocument

from pam.common.config import settings

logger = structlog.get_logger()


@dataclass
class ChunkResult:
    """A single chunk produced from a document."""

    content: str
    content_hash: str
    section_path: str | None
    segment_type: str  # "text", "table", "code"
    position: int


def chunk_document(doc: DoclingDocument, max_tokens: int | None = None) -> list[ChunkResult]:
    """Chunk a DoclingDocument using Docling's HybridChunker.

    Args:
        doc: Parsed DoclingDocument from Docling.
        max_tokens: Max tokens per chunk. Defaults to settings.chunk_size_tokens.

    Returns:
        List of ChunkResult objects with content, metadata, and position.
    """
    from docling.chunking import HybridChunker

    max_tokens = max_tokens or settings.chunk_size_tokens

    chunker = HybridChunker(
        tokenizer="sentence-transformers/all-MiniLM-L6-v2",
        max_tokens=max_tokens,
    )

    chunks = list(chunker.chunk(doc))
    results = []

    for i, chunk in enumerate(chunks):
        text = chunk.text
        if not text.strip():
            continue

        # Extract section path from chunk metadata/headings
        section_path = _extract_section_path(chunk)

        # Determine segment type
        segment_type = "text"
        if hasattr(chunk, "meta") and chunk.meta:
            meta = chunk.meta
            if hasattr(meta, "doc_items"):
                for item in meta.doc_items:
                    label = getattr(item, "label", None)
                    if label and "table" in str(label).lower():
                        segment_type = "table"
                        break
                    if label and "code" in str(label).lower():
                        segment_type = "code"
                        break

        content_hash = hashlib.sha256(text.encode()).hexdigest()
        results.append(
            ChunkResult(
                content=text,
                content_hash=content_hash,
                section_path=section_path,
                segment_type=segment_type,
                position=i,
            )
        )

    logger.info("chunk_document", chunk_count=len(results), max_tokens=max_tokens)
    return results


def _extract_section_path(chunk) -> str | None:
    """Extract hierarchical section path from a Docling chunk."""
    if hasattr(chunk, "meta") and chunk.meta:
        headings = getattr(chunk.meta, "headings", None)
        if headings:
            return " > ".join(headings)
    return None
