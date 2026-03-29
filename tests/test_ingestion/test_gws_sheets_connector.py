"""Tests for GWS Sheets CLI connector."""

import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector


DRIVE_LIST_RESPONSE = {
    "files": [
        {"id": "sheet1", "name": "Budget", "webViewLink": "https://sheets.google.com/sheet1", "modifiedTime": "2024-06-01T00:00:00Z"},
    ],
}

SPREADSHEET_RESPONSE = {
    "properties": {"title": "Budget"},
    "sheets": [
        {
            "properties": {"title": "Q1"},
            "data": [{"rowData": [
                {"values": [{"formattedValue": "Category"}, {"formattedValue": "Amount"}]},
                {"values": [{"formattedValue": "Rent"}, {"formattedValue": "2000"}]},
            ]}],
        }
    ],
}


@pytest.fixture
def connector():
    return GwsSheetsConnector(folder_ids=["folder_abc"])


class TestListDocuments:
    async def test_returns_sheets_from_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=DRIVE_LIST_RESPONSE):
            docs = await connector.list_documents()
        assert len(docs) == 1
        assert docs[0].source_id == "sheet1"
        assert docs[0].title == "Budget"

    async def test_handles_empty_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={"files": []}):
            docs = await connector.list_documents()
        assert docs == []


class TestFetchDocument:
    async def test_returns_json_with_sheet_data(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=SPREADSHEET_RESPONSE):
            doc = await connector.fetch_document("sheet1")

        assert isinstance(doc, RawDocument)
        assert doc.content_type == "application/vnd.google-sheets+json"
        assert doc.source_id == "sheet1"
        parsed = json.loads(doc.content)
        assert "title" in parsed
        assert "tabs" in parsed

    async def test_calls_sheets_api(self, connector):
        mock_run = AsyncMock(return_value=SPREADSHEET_RESPONSE)
        with patch.object(connector, "run_cli", mock_run):
            await connector.fetch_document("sheet123")
        args = mock_run.call_args[0][0]
        assert "spreadsheets" in " ".join(args)
        assert "sheet123" in " ".join(args)


class TestGetContentHash:
    async def test_hashes_fetched_content(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=SPREADSHEET_RESPONSE):
            result = await connector.get_content_hash("sheet1")

        # Re-fetch to compute expected hash
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=SPREADSHEET_RESPONSE):
            doc = await connector.fetch_document("sheet1")
        expected = hashlib.sha256(doc.content).hexdigest()
        assert result == expected
