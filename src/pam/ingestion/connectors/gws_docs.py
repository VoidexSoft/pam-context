"""Google Docs connector via gws CLI."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector

logger = structlog.get_logger()

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GwsDocsConnector(CliConnector):
    """Ingest Google Docs via gws CLI, exporting as DOCX."""

    cli_binary = "gws"

    def __init__(self, folder_ids: list[str] | None = None) -> None:
        self.folder_ids = folder_ids or []

    async def list_documents(self) -> list[DocumentInfo]:
        docs: list[DocumentInfo] = []

        for folder_id in self.folder_ids:
            query = f'mimeType="{GOOGLE_DOC_MIME}" and "{folder_id}" in parents'
            params = json.dumps({"q": query, "pageSize": 100})
            result = await self.run_cli([
                "drive", "files", "list",
                "--params", params,
                "--page-all",
            ])
            for f in result.get("files", []):
                modified_at = (
                    datetime.fromisoformat(f["modifiedTime"])
                    if f.get("modifiedTime") else None
                )
                docs.append(DocumentInfo(
                    source_id=f["id"],
                    title=f["name"],
                    source_url=f.get("webViewLink"),
                    modified_at=modified_at,
                ))

        logger.info("gws_docs_list_documents", folder_count=len(self.folder_ids), count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        params = json.dumps({
            "fileId": source_id,
            "mimeType": DOCX_MIME,
        })
        content = await self.run_cli_raw([
            "drive", "files", "export",
            "--params", params,
        ])
        return RawDocument(
            content=content,
            content_type=DOCX_MIME,
            source_id=source_id,
            title=source_id,
        )

    async def get_content_hash(self, source_id: str) -> str:
        params = json.dumps({"fileId": source_id, "fields": "md5Checksum"})
        result = await self.run_cli([
            "drive", "files", "get",
            "--params", params,
        ])
        md5: str | None = result.get("md5Checksum")
        if md5:
            return md5
        content = await self.run_cli_raw([
            "drive", "files", "export",
            "--params", json.dumps({"fileId": source_id, "mimeType": DOCX_MIME}),
        ])
        return hashlib.sha256(content).hexdigest()
