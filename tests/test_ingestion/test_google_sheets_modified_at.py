"""Phase 10: Tests for Google Sheets connector modified_at population."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.common.models import RawDocument
from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector


def _mock_execute(return_value):
    req = MagicMock()
    req.execute.return_value = return_value
    return req


def _make_sync_loop():
    loop = MagicMock()
    loop.run_in_executor = AsyncMock(side_effect=lambda _, fn: fn())
    return loop


@pytest.fixture
def connector():
    return GoogleSheetsConnector(
        spreadsheet_ids=["sheet1"],
        credentials_path="/fake/creds.json",
    )


@pytest.fixture
def mock_sheets_service():
    service = MagicMock()
    service.spreadsheets.return_value = service
    return service


@pytest.fixture
def mock_drive_service():
    service = MagicMock()
    service.files.return_value = service
    return service


@pytest.fixture
def patch_loop():
    loop = _make_sync_loop()
    with patch(
        "pam.ingestion.connectors.google_sheets.asyncio.get_running_loop",
        return_value=loop,
    ):
        yield loop


def _spreadsheet_response(title="Test Sheet"):
    """Minimal Sheets API spreadsheet response."""
    return {
        "properties": {"title": title},
        "sheets": [
            {
                "properties": {"title": "Sheet1"},
                "data": [{"rowData": [{"values": [{"formattedValue": "hello"}]}]}],
            }
        ],
    }


class TestFetchDocumentModifiedAt:
    async def test_fetch_populates_modified_at_from_drive_api(
        self, connector, mock_sheets_service, mock_drive_service, patch_loop
    ):
        """Phase 10: modified_at is parsed from Drive API modifiedTime field."""
        mock_sheets_service.get.return_value = _mock_execute(_spreadsheet_response())
        mock_drive_service.get.return_value = _mock_execute(
            {"modifiedTime": "2024-08-15T10:30:00.000Z"}
        )
        connector._sheets_service = mock_sheets_service
        connector._service = mock_drive_service

        doc = await connector.fetch_document("sheet1")

        assert isinstance(doc, RawDocument)
        assert doc.modified_at is not None
        assert isinstance(doc.modified_at, datetime)
        assert doc.modified_at.year == 2024
        assert doc.modified_at.month == 8
        assert doc.modified_at.day == 15

    async def test_fetch_modified_at_none_when_missing(
        self, connector, mock_sheets_service, mock_drive_service, patch_loop
    ):
        """Phase 10: modified_at is None when modifiedTime absent from Drive API."""
        mock_sheets_service.get.return_value = _mock_execute(_spreadsheet_response())
        mock_drive_service.get.return_value = _mock_execute({})
        connector._sheets_service = mock_sheets_service
        connector._service = mock_drive_service

        doc = await connector.fetch_document("sheet1")

        assert isinstance(doc, RawDocument)
        assert doc.modified_at is None
