"""Google Sheets connector — reads spreadsheets via the Sheets API.

Uses region detection to identify tables, notes, and config sections within sheets,
then converts each region into KnowledgeSegments.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.base import BaseConnector
from pam.ingestion.connectors.sheets_region_detector import SheetRegion, detect_regions

logger = structlog.get_logger()


class GoogleSheetsConnector(BaseConnector):
    """Connector for Google Sheets via the Sheets API.

    Requires Google OAuth2 credentials (configured via settings).
    """

    def __init__(
        self,
        spreadsheet_ids: list[str] | None = None,
        folder_id: str | None = None,
        credentials_path: str | None = None,
    ) -> None:
        self.spreadsheet_ids = spreadsheet_ids or []
        self.folder_id = folder_id
        self.credentials_path = credentials_path
        self._service = None
        self._sheets_service = None

    def _get_drive_service(self):
        """Lazy-init Google Drive API v3 client."""
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            creds = Credentials.from_authorized_user_file(self.credentials_path)
            self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _get_sheets_service(self):
        """Lazy-init Google Sheets API v4 client."""
        if self._sheets_service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            creds = Credentials.from_authorized_user_file(self.credentials_path)
            self._sheets_service = build("sheets", "v4", credentials=creds)
        return self._sheets_service

    async def list_documents(self) -> list[DocumentInfo]:
        """List spreadsheets from specified IDs or folder."""
        loop = asyncio.get_running_loop()
        docs = []

        if self.spreadsheet_ids:
            sheets_svc = self._get_sheets_service()
            for sid in self.spreadsheet_ids:
                request = sheets_svc.spreadsheets().get(spreadsheetId=sid, fields="properties")
                meta = await loop.run_in_executor(None, request.execute)
                props = meta["properties"]
                docs.append(
                    DocumentInfo(
                        source_id=sid,
                        title=props.get("title", sid),
                        source_url=f"https://docs.google.com/spreadsheets/d/{sid}",
                    )
                )
        elif self.folder_id:
            drive = self._get_drive_service()
            query = (
                f"'{self.folder_id}' in parents and "
                "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
            )
            request = drive.files().list(q=query, fields="files(id,name,webViewLink)")
            results = await loop.run_in_executor(None, request.execute)
            for f in results.get("files", []):
                docs.append(
                    DocumentInfo(
                        source_id=f["id"],
                        title=f["name"],
                        source_url=f.get("webViewLink"),
                    )
                )

        logger.info("sheets_list_documents", count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch all tabs from a spreadsheet and return as JSON with detected regions."""
        loop = asyncio.get_running_loop()
        sheets_svc = self._get_sheets_service()

        # Get spreadsheet metadata and all cell values
        request = sheets_svc.spreadsheets().get(
            spreadsheetId=source_id,
            includeGridData=True,
        )
        spreadsheet = await loop.run_in_executor(None, request.execute)

        title = spreadsheet["properties"]["title"]
        tabs_data = {}

        for sheet in spreadsheet.get("sheets", []):
            tab_name = sheet["properties"]["title"]
            grid_data = sheet.get("data", [{}])[0]
            rows = []

            for row_data in grid_data.get("rowData", []):
                cells = []
                for cell in row_data.get("values", []):
                    # Get the formatted/displayed value
                    cells.append(cell.get("formattedValue", ""))
                rows.append(cells)

            # Detect regions for this tab
            regions = detect_regions(rows, tab_name)
            tabs_data[tab_name] = {
                "rows": rows,
                "regions": [_region_to_dict(r) for r in regions],
            }

        content = json.dumps({"title": title, "tabs": tabs_data}, ensure_ascii=False).encode()

        return RawDocument(
            content=content,
            content_type="application/vnd.google-sheets+json",
            source_id=source_id,
            title=title,
            source_url=f"https://docs.google.com/spreadsheets/d/{source_id}",
            metadata={"tab_count": len(tabs_data)},
        )

    async def get_content_hash(self, source_id: str) -> str:
        """Get hash of spreadsheet content for change detection."""
        doc = await self.fetch_document(source_id)
        return hashlib.sha256(doc.content).hexdigest()


class LocalSheetsConnector(BaseConnector):
    """Local connector for testing — reads sheet data from Python dicts (mock fixtures).

    This allows testing the full pipeline without Google API access.
    """

    def __init__(self, sheets: dict[str, dict]) -> None:
        """Initialize with a dict of {source_id: sheet_data} where sheet_data has 'title' and 'tabs'."""
        self.sheets = sheets

    async def list_documents(self) -> list[DocumentInfo]:
        return [
            DocumentInfo(source_id=sid, title=data["title"])
            for sid, data in self.sheets.items()
        ]

    async def fetch_document(self, source_id: str) -> RawDocument:
        sheet_data = self.sheets[source_id]
        title = sheet_data["title"]
        tabs = sheet_data["tabs"]

        tabs_with_regions = {}
        for tab_name, rows in tabs.items():
            regions = detect_regions(rows, tab_name)
            tabs_with_regions[tab_name] = {
                "rows": rows,
                "regions": [_region_to_dict(r) for r in regions],
            }

        content = json.dumps({"title": title, "tabs": tabs_with_regions}, ensure_ascii=False).encode()

        return RawDocument(
            content=content,
            content_type="application/vnd.google-sheets+json",
            source_id=source_id,
            title=title,
            metadata={"tab_count": len(tabs)},
        )

    async def get_content_hash(self, source_id: str) -> str:
        doc = await self.fetch_document(source_id)
        return hashlib.sha256(doc.content).hexdigest()


def _region_to_dict(region: SheetRegion) -> dict:
    return {
        "type": region.type,
        "start_row": region.start_row,
        "end_row": region.end_row,
        "headers": region.headers,
        "rows": region.rows,
        "raw_text": region.raw_text,
    }
