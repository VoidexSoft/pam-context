"""Document parser using Docling for layout-aware parsing."""

import io
import tempfile
from pathlib import Path

import structlog
from docling.datamodel.document import DoclingDocument
from docling.document_converter import DocumentConverter

from pam.common.models import RawDocument
from pam.ingestion.parsers.base import BaseParser, ParsedDocument, ParsedImage, ParsedTable

logger = structlog.get_logger()


class DoclingParser(BaseParser):
    """Parses documents (DOCX, PDF, Markdown) into Docling's structured format."""

    def __init__(self) -> None:
        self._converter = DocumentConverter()

    def parse(self, raw_document: RawDocument) -> ParsedDocument:
        """Parse a raw document into a ParsedDocument.

        For DOCX/PDF: writes to temp file, runs Docling converter.
        For Markdown: writes to temp file with .md extension.
        """
        ext_map = {
            "text/markdown": ".md",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/pdf": ".pdf",
        }
        ext = ext_map.get(raw_document.content_type, ".bin")

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(raw_document.content)
            tmp_path = Path(tmp.name)

        try:
            result = self._converter.convert(str(tmp_path))
            docling_doc = result.document
            logger.info(
                "docling_parse",
                source_id=raw_document.source_id,
                content_type=raw_document.content_type,
            )

            # Extract images
            images = self._extract_images(docling_doc)

            # Extract tables
            tables = self._extract_tables(docling_doc)

            return ParsedDocument(
                markdown_content=docling_doc.export_to_markdown(),
                images=images,
                tables=tables,
                _docling_doc=docling_doc,
            )
        except Exception:
            logger.exception("docling_parse_error", source_id=raw_document.source_id)
            raise
        finally:
            tmp_path.unlink(missing_ok=True)

    def _extract_images(self, doc: DoclingDocument) -> list[ParsedImage]:
        """Extract images from a DoclingDocument."""
        images: list[ParsedImage] = []
        pictures = getattr(doc, "pictures", None)
        if not pictures:
            return images

        for i, picture in enumerate(pictures):
            try:
                pil_image = picture.get_image(doc)
                if pil_image is None:
                    continue
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                caption = getattr(picture, "caption", None)
                if hasattr(caption, "text"):
                    caption = caption.text
                images.append(
                    ParsedImage(
                        image_data=buf.getvalue(),
                        caption=caption if isinstance(caption, str) else None,
                        position=i,
                    )
                )
            except Exception:
                logger.debug("image_extraction_failed", image_index=i, exc_info=True)
                continue

        return images

    def _extract_tables(self, doc: DoclingDocument) -> list[ParsedTable]:
        """Extract tables from a DoclingDocument."""
        tables_list: list[ParsedTable] = []
        tables = getattr(doc, "tables", None)
        if not tables:
            return tables_list

        for i, table in enumerate(tables):
            try:
                md = table.export_to_markdown(doc)
                if not md or not md.strip():
                    continue
                caption = getattr(table, "caption", None)
                if hasattr(caption, "text"):
                    caption = caption.text
                tables_list.append(
                    ParsedTable(
                        markdown=md,
                        caption=caption if isinstance(caption, str) else None,
                        position=i,
                    )
                )
            except Exception:
                logger.debug("table_extraction_failed", table_index=i, exc_info=True)
                continue

        return tables_list
