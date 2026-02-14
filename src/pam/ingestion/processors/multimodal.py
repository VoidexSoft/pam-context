"""Multimodal document processing — extracts descriptions from images and tables."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass

import structlog

from pam.common.llm.base import BaseLLMClient
from pam.ingestion.chunkers.hybrid_chunker import ChunkResult
from pam.ingestion.processors.prompts import (
    IMAGE_ANALYSIS_PROMPT,
    IMAGE_ANALYSIS_SYSTEM,
    IMAGE_CHUNK_TEMPLATE,
    TABLE_ANALYSIS_PROMPT,
    TABLE_ANALYSIS_SYSTEM,
    TABLE_CHUNK_TEMPLATE,
)

logger = structlog.get_logger()


@dataclass
class MultimodalConfig:
    """Configuration for multimodal processing."""

    enable_image_processing: bool = True
    enable_table_processing: bool = True
    context_window_chars: int = 2000


class MultimodalProcessor:
    """Processes images and tables from parsed documents into searchable text segments."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        config: MultimodalConfig | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._config = config or MultimodalConfig()

    async def process_document(
        self,
        doc,  # DoclingDocument
        text_chunks: list[ChunkResult],
    ) -> list[ChunkResult]:
        """Extract images/tables from a DoclingDocument, generate descriptions, return as additional chunks.

        Args:
            doc: A DoclingDocument from Docling parsing.
            text_chunks: Existing text chunks for context extraction.

        Returns:
            Additional ChunkResult objects for images and tables.
        """
        results: list[ChunkResult] = []
        base_position = len(text_chunks)

        if self._config.enable_image_processing:
            image_chunks = await self._process_images(doc, text_chunks, base_position)
            results.extend(image_chunks)
            base_position += len(image_chunks)

        if self._config.enable_table_processing:
            table_chunks = await self._process_tables(doc, text_chunks, base_position)
            results.extend(table_chunks)

        logger.info(
            "multimodal_processing_complete",
            images=sum(1 for r in results if r.segment_type == "image"),
            tables=sum(1 for r in results if r.segment_type == "table"),
        )

        return results

    async def _process_images(
        self,
        doc,
        text_chunks: list[ChunkResult],
        base_position: int,
    ) -> list[ChunkResult]:
        """Process images from a DoclingDocument."""
        results: list[ChunkResult] = []

        pictures = getattr(doc, "pictures", None)
        if not pictures:
            return results

        for i, picture in enumerate(pictures):
            try:
                # Get image data from DoclingDocument
                pil_image = picture.get_image(doc)
                if pil_image is None:
                    continue

                # Convert PIL Image to PNG bytes
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                image_bytes = buf.getvalue()

                # Extract context from nearby chunks
                context = self._extract_context(text_chunks, i)

                # Call VLM for image analysis
                if not self._llm_client.supports_vision:
                    logger.warning("llm_client_no_vision_support", image_index=i)
                    continue

                prompt = IMAGE_ANALYSIS_PROMPT.format(context=context)
                response = await self._llm_client.complete_with_vision(
                    messages=[{"role": "user", "content": prompt}],
                    images=[image_bytes],
                    system=IMAGE_ANALYSIS_SYSTEM,
                    max_tokens=1024,
                )

                parsed = self._robust_json_parse(response.text)
                if not parsed:
                    logger.warning("image_analysis_parse_failed", image_index=i)
                    continue

                # Format into chunk text
                content = IMAGE_CHUNK_TEMPLATE.format(
                    description=parsed.get("description", "Image"),
                    key_elements=", ".join(parsed.get("key_elements", [])),
                    relevance=parsed.get("relevance", ""),
                )

                content_hash = hashlib.sha256(content.encode()).hexdigest()
                results.append(
                    ChunkResult(
                        content=content,
                        content_hash=content_hash,
                        section_path=None,
                        segment_type="image",
                        position=base_position + i,
                    )
                )

            except Exception:
                logger.warning("image_processing_failed", image_index=i, exc_info=True)
                continue

        return results

    async def _process_tables(
        self,
        doc,
        text_chunks: list[ChunkResult],
        base_position: int,
    ) -> list[ChunkResult]:
        """Process tables from a DoclingDocument."""
        results: list[ChunkResult] = []

        tables = getattr(doc, "tables", None)
        if not tables:
            return results

        for i, table in enumerate(tables):
            try:
                # Export table to markdown
                table_md = table.export_to_markdown(doc)
                if not table_md or not table_md.strip():
                    continue

                # Extract context from nearby chunks
                context = self._extract_context(text_chunks, i)

                prompt = TABLE_ANALYSIS_PROMPT.format(
                    context=context,
                    table_body=table_md,
                )
                response = await self._llm_client.complete(
                    messages=[{"role": "user", "content": prompt}],
                    system=TABLE_ANALYSIS_SYSTEM,
                    max_tokens=1024,
                )

                parsed = self._robust_json_parse(response.text)
                if not parsed:
                    logger.warning("table_analysis_parse_failed", table_index=i)
                    continue

                # Format into chunk text
                content = TABLE_CHUNK_TEMPLATE.format(
                    summary=parsed.get("summary", "Table"),
                    key_findings=", ".join(parsed.get("key_findings", [])),
                    table_body=table_md,
                )

                content_hash = hashlib.sha256(content.encode()).hexdigest()
                results.append(
                    ChunkResult(
                        content=content,
                        content_hash=content_hash,
                        section_path=None,
                        segment_type="table",
                        position=base_position + i,
                    )
                )

            except Exception:
                logger.warning("table_processing_failed", table_index=i, exc_info=True)
                continue

        return results

    def _extract_context(self, text_chunks: list[ChunkResult], position: int) -> str:
        """Extract surrounding text context for multimodal analysis."""
        if not text_chunks:
            return "No surrounding text available."

        # Use chunks near the position as context
        max_chars = self._config.context_window_chars
        context_parts: list[str] = []
        current_chars = 0

        # Start from the position (clamped) and work outward
        start = min(position, len(text_chunks) - 1)
        for offset in range(len(text_chunks)):
            for idx in [start - offset, start + offset]:
                if 0 <= idx < len(text_chunks) and current_chars < max_chars:
                    chunk_text = text_chunks[idx].content
                    remaining = max_chars - current_chars
                    context_parts.append(chunk_text[:remaining])
                    current_chars += len(chunk_text[:remaining])
                    if current_chars >= max_chars:
                        break
            if current_chars >= max_chars:
                break

        return " ".join(context_parts) if context_parts else "No surrounding text available."

    def _robust_json_parse(self, response: str) -> dict | None:
        """Multi-strategy JSON parsing with fallbacks."""
        text = response.strip()

        # Strategy 1: Direct parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Strategy 2: Strip markdown code fences
        if "```" in text:
            # Remove ```json ... ``` or ``` ... ```
            cleaned = re.sub(r"```(?:json)?\s*", "", text)
            cleaned = re.sub(r"\s*```", "", cleaned).strip()
            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find JSON object with regex
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return None
