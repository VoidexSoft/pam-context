"""Google Docs connector — exports Google Docs as DOCX via Drive API."""

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
        from googleapiclient.discovery import build

        if self._credentials_path:
            creds = Credentials.from_authorized_user_file(str(self._credentials_path))
        else:
            raise ValueError("Google credentials path required. Set up OAuth2 first.")

        self._service = build("drive", "v3", credentials=creds)
        return self._service

    async def list_documents(self) -> list[DocumentInfo]:
        service = self._get_service()
        docs = []

        for folder_id in self.folder_ids:
            query = f"'{folder_id}' in parents and mimeType='{GOOGLE_DOC_MIME}' and trashed=false"
            results = (
                service.files()
                .list(
                    q=query,
                    fields="files(id, name, owners, webViewLink, modifiedTime)",
                    pageSize=100,
                )
                .execute()
            )

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

        logger.info("gdocs_list_documents", folder_count=len(self.folder_ids), doc_count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        service = self._get_service()

        # Get metadata
        file_meta = service.files().get(fileId=source_id, fields="name, owners, webViewLink").execute()

        # Export as DOCX
        content = service.files().export(fileId=source_id, mimeType=DOCX_MIME).execute()

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
        # Use Drive API md5Checksum for change detection
        file_meta = service.files().get(fileId=source_id, fields="md5Checksum").execute()
        md5 = file_meta.get("md5Checksum")
        if md5:
            return md5
        # Fallback: export and hash (Google Docs don't have md5Checksum)
        content = service.files().export(fileId=source_id, mimeType=DOCX_MIME).execute()
        return hashlib.sha256(content).hexdigest()
