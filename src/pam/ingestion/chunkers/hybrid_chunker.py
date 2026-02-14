"""Chunking using Docling's HybridChunker with configurable token size."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import structlog
from docling_core.types.doc import DoclingDocument

from pam.common.config import settings
from pam.ingestion.parsers.base import ParsedDocument

logger = structlog.get_logger()


@dataclass
class ChunkResult:
    """A single chunk produced from a document."""

    content: str
    content_hash: str
    section_path: str | None
    segment_type: str  # "text", "table", "code"
    position: int


def chunk_document(doc: DoclingDocument | ParsedDocument, max_tokens: int | None = None) -> list[ChunkResult]:
    """Chunk a DoclingDocument or ParsedDocument using Docling's HybridChunker.

    Args:
        doc: Parsed DoclingDocument or ParsedDocument.
        max_tokens: Max tokens per chunk. Defaults to settings.chunk_size_tokens.

    Returns:
        List of ChunkResult objects with content, metadata, and position.
    """
    # If ParsedDocument, check for docling_doc or fall back to markdown chunking
    if isinstance(doc, ParsedDocument):
        if doc._docling_doc is not None:
            doc = doc._docling_doc
        else:
            return chunk_markdown(doc.markdown_content, max_tokens)

    from docling.chunking import HybridChunker

    max_tokens = max_tokens or settings.chunk_size_tokens

    chunker = HybridChunker.model_validate({
        "tokenizer": "sentence-transformers/all-MiniLM-L6-v2",
        "max_tokens": max_tokens,
    })

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


def chunk_markdown(text: str, max_tokens: int | None = None) -> list[ChunkResult]:
    """Simple markdown chunking by headers and paragraphs.

    Used when Docling's HybridChunker is not available (e.g., MinerU output).
    """
    max_tokens = max_tokens or settings.chunk_size_tokens
    # Approximate: 1 token ~ 4 chars
    max_chars = max_tokens * 4

    # Split by headers first
    sections = re.split(r"(?=^#{1,6}\s)", text, flags=re.MULTILINE)

    results: list[ChunkResult] = []
    position = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract heading if present
        heading_match = re.match(r"^(#{1,6})\s+(.+?)$", section, re.MULTILINE)
        section_path = heading_match.group(2) if heading_match else None

        # If section fits in one chunk, use it directly
        if len(section) <= max_chars:
            content_hash = hashlib.sha256(section.encode()).hexdigest()
            results.append(
                ChunkResult(
                    content=section,
                    content_hash=content_hash,
                    section_path=section_path,
                    segment_type="text",
                    position=position,
                )
            )
            position += 1
        else:
            # Split long sections by paragraphs
            paragraphs = section.split("\n\n")
            current_chunk: list[str] = []
            current_len = 0

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                if current_len + len(para) > max_chars and current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
                    results.append(
                        ChunkResult(
                            content=chunk_text,
                            content_hash=content_hash,
                            section_path=section_path,
                            segment_type="text",
                            position=position,
                        )
                    )
                    position += 1
                    current_chunk = []
                    current_len = 0

                current_chunk.append(para)
                current_len += len(para)

            if current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
                results.append(
                    ChunkResult(
                        content=chunk_text,
                        content_hash=content_hash,
                        section_path=section_path,
                        segment_type="text",
                        position=position,
                    )
                )
                position += 1

    logger.info("chunk_markdown", chunk_count=len(results), max_tokens=max_tokens)
    return results


def _extract_section_path(chunk) -> str | None:
    """Extract hierarchical section path from a Docling chunk."""
    if hasattr(chunk, "meta") and chunk.meta:
        headings = getattr(chunk.meta, "headings", None)
        if headings:
            return " > ".join(headings)
    return None
