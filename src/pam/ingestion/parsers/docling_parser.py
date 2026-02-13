"""Document parser using Docling for layout-aware parsing."""

import tempfile
from pathlib import Path

import structlog
from docling.datamodel.document import DoclingDocument
from docling.document_converter import DocumentConverter

from pam.common.models import RawDocument

logger = structlog.get_logger()


class DoclingParser:
    """Parses documents (DOCX, PDF, Markdown) into Docling's structured format."""

    def __init__(self) -> None:
        self._converter = DocumentConverter()

    def parse(self, raw_document: RawDocument) -> "DoclingDocument":
        """Parse a raw document into a DoclingDocument.

        For DOCX/PDF: writes to temp file, runs Docling converter.
        For Markdown: writes to temp file with .md extension.
        """
        # Determine file extension
        ext_map = {
            "text/markdown": ".md",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/pdf": ".pdf",
        }
        ext = ext_map.get(raw_document.content_type, ".bin")

        # Write to temp file (Docling needs a file path)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(raw_document.content)
            tmp_path = Path(tmp.name)

        try:
            result = self._converter.convert(str(tmp_path))
            logger.info(
                "docling_parse",
                source_id=raw_document.source_id,
                content_type=raw_document.content_type,
            )
            return result.document
        except Exception:
            logger.exception("docling_parse_error", source_id=raw_document.source_id)
            raise
        finally:
            tmp_path.unlink(missing_ok=True)
