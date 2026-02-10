"""Markdown file connector — reads .md files from a local directory."""

import hashlib
from pathlib import Path

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.base import BaseConnector

logger = structlog.get_logger()


class MarkdownConnector(BaseConnector):
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise ValueError(f"Directory does not exist: {self.directory}")

    async def list_documents(self) -> list[DocumentInfo]:
        docs = []
        for path in sorted(self.directory.rglob("*.md")):
            stat = path.stat()
            docs.append(
                DocumentInfo(
                    source_id=str(path),
                    title=path.stem,
                    source_url=f"file://{path}",
                    modified_at=None,  # Could use stat.st_mtime but keeping simple
                )
            )
        logger.info("markdown_list_documents", directory=str(self.directory), count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        path = Path(source_id)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {source_id}")

        content = path.read_bytes()
        return RawDocument(
            content=content,
            content_type="text/markdown",
            source_id=source_id,
            title=path.stem,
            source_url=f"file://{path}",
        )

    async def get_content_hash(self, source_id: str) -> str:
        path = Path(source_id)
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest()
