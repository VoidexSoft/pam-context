"""Google Docs connector — exports Google Docs as DOCX via Drive API."""

import asyncio
import hashlib
from pathlib import Path

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.base import BaseConnector

logger = structlog.get_logger()

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GoogleDocsConnector(BaseConnector):
    """Connects to Google Drive and exports Google Docs as DOCX for parsing.

    Requires Google OAuth2 credentials. For Phase 1, use manual trigger only (no webhooks).
    """

    def __init__(self, credentials_path: str | Path | None = None, folder_ids: list[str] | None = None) -> None:
        self.folder_ids = folder_ids or []
        self._service = None
        self._credentials_path = credentials_path

    def _get_service(self):
        """Lazy-init the Google Drive service."""
        if self._service is not None:
            return self._service

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build  # type: ignore[import-untyped]

        if self._credentials_path:
            creds = Credentials.from_authorized_user_file(str(self._credentials_path))
        else:
            raise ValueError("Google credentials path required. Set up OAuth2 first.")

        self._service = build("drive", "v3", credentials=creds)
        return self._service

    async def list_documents(self) -> list[DocumentInfo]:
        service = self._get_service()
        loop = asyncio.get_running_loop()
        docs = []

        for folder_id in self.folder_ids:
            query = f"'{folder_id}' in parents and mimeType='{GOOGLE_DOC_MIME}' and trashed=false"
            page_token = None
            while True:
                request = service.files().list(
                    q=query,
                    fields="nextPageToken,files(id, name, owners, webViewLink, modifiedTime)",
                    pageSize=100,
                    pageToken=page_token,
                )
                results = await loop.run_in_executor(None, request.execute)

                for f in results.get("files", []):
                    owner = f.get("owners", [{}])[0].get("emailAddress") if f.get("owners") else None
                    docs.append(
                        DocumentInfo(
                            source_id=f["id"],
                            title=f["name"],
                            owner=owner,
                            source_url=f.get("webViewLink"),
                        )
                    )

                page_token = results.get("nextPageToken")
                if not page_token:
                    break

        logger.info("gdocs_list_documents", folder_count=len(self.folder_ids), doc_count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        service = self._get_service()
        loop = asyncio.get_running_loop()

        # Get metadata
        meta_request = service.files().get(fileId=source_id, fields="name, owners, webViewLink")
        file_meta = await loop.run_in_executor(None, meta_request.execute)

        # Export as DOCX
        export_request = service.files().export(fileId=source_id, mimeType=DOCX_MIME)
        content = await loop.run_in_executor(None, export_request.execute)

        owner = file_meta.get("owners", [{}])[0].get("emailAddress") if file_meta.get("owners") else None
        return RawDocument(
            content=content,
            content_type=DOCX_MIME,
            source_id=source_id,
            title=file_meta["name"],
            source_url=file_meta.get("webViewLink"),
            owner=owner,
        )

    async def get_content_hash(self, source_id: str) -> str:
        service = self._get_service()
        loop = asyncio.get_running_loop()

        # Use Drive API md5Checksum for change detection
        meta_request = service.files().get(fileId=source_id, fields="md5Checksum")
        file_meta = await loop.run_in_executor(None, meta_request.execute)
        md5: str | None = file_meta.get("md5Checksum")
        if md5:
            return md5
        # Fallback: export and hash (Google Docs don't have md5Checksum)
        export_request = service.files().export(fileId=source_id, mimeType=DOCX_MIME)
        content = await loop.run_in_executor(None, export_request.execute)
        return hashlib.sha256(content).hexdigest()
