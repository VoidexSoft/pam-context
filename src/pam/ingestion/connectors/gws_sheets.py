"""Google Sheets connector via gws CLI."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector

logger = structlog.get_logger()

SHEETS_MIME = "application/vnd.google-apps.spreadsheet"


class GwsSheetsConnector(CliConnector):
    """Ingest Google Sheets via gws CLI."""

    cli_binary = "gws"

    def __init__(self, folder_ids: list[str] | None = None) -> None:
        self.folder_ids = folder_ids or []

    async def list_documents(self) -> list[DocumentInfo]:
        docs: list[DocumentInfo] = []

        for folder_id in self.folder_ids:
            query = f'mimeType="{SHEETS_MIME}" and "{folder_id}" in parents'
            params = json.dumps(
                {
                    "q": query,
                    "pageSize": 100,
                    "fields": "files(id,name,owners,webViewLink,modifiedTime),nextPageToken",
                }
            )
            result = await self.run_cli(
                [
                    "drive",
                    "files",
                    "list",
                    "--params",
                    params,
                    "--page-all",
                ]
            )
            for f in result.get("files", []):
                modified_at = datetime.fromisoformat(f["modifiedTime"]) if f.get("modifiedTime") else None
                owner = f.get("owners", [{}])[0].get("emailAddress") if f.get("owners") else None
                docs.append(
                    DocumentInfo(
                        source_id=f["id"],
                        title=f["name"],
                        owner=owner,
                        source_url=f.get("webViewLink"),
                        modified_at=modified_at,
                    )
                )

        logger.info("gws_sheets_list_documents", folder_count=len(self.folder_ids), count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        params = json.dumps({"spreadsheetId": source_id, "includeGridData": True})
        data = await self.run_cli(
            [
                "sheets",
                "spreadsheets",
                "get",
                "--params",
                params,
            ]
        )

        title = data.get("properties", {}).get("title", source_id)
        tabs: dict[str, dict] = {}

        for sheet in data.get("sheets", []):
            tab_name = sheet.get("properties", {}).get("title", "Sheet")
            rows: list[list[str]] = []
            for grid in sheet.get("data", []):
                for row_data in grid.get("rowData", []):
                    cells = [cell.get("formattedValue", "") for cell in row_data.get("values", [])]
                    rows.append(cells)

            # Try to use detect_regions if available, otherwise just store rows
            try:
                from pam.ingestion.connectors.sheets_region_detector import detect_regions

                regions = detect_regions(rows) if rows else []
                tabs[tab_name] = {
                    "rows": rows,
                    "regions": [
                        {
                            "type": r.type,
                            "start_row": r.start_row,
                            "end_row": r.end_row,
                            "headers": r.headers,
                            "rows": r.rows,
                            "raw_text": r.raw_text,
                        }
                        for r in regions
                    ],
                }
            except ImportError:
                tabs[tab_name] = {"rows": rows, "regions": []}

        content_json = json.dumps({"title": title, "tabs": tabs}, ensure_ascii=False)

        return RawDocument(
            content=content_json.encode(),
            content_type="application/vnd.google-sheets+json",
            source_id=source_id,
            title=title,
            metadata={"tab_count": len(tabs)},
        )

    async def get_content_hash(self, source_id: str) -> str:
        doc = await self.fetch_document(source_id)
        return hashlib.sha256(doc.content).hexdigest()
