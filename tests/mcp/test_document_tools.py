"""Tests for MCP document tools."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_get_document_by_title(mock_services: PamServices):
    """pam_get_document fetches a document by title."""
    doc_id = uuid.uuid4()
    mock_doc = MagicMock()
    mock_doc.id = doc_id
    mock_doc.title = "Q1 Report"
    mock_doc.source_type = "markdown"
    mock_doc.source_id = "/docs/q1.md"
    mock_doc.created_at = datetime(2026, 1, 15, tzinfo=UTC)

    mock_segment = MagicMock()
    mock_segment.content = "Revenue grew 15%"
    mock_segment.section_path = "financials"
    mock_segment.position = 0

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_doc

    mock_seg_result = MagicMock()
    mock_seg_result.scalars.return_value.all.return_value = [mock_segment]

    mock_session.execute = AsyncMock(side_effect=[mock_result, mock_seg_result])
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_get_document

    result = await _pam_get_document(document_title="Q1 Report", source_id=None)
    parsed = json.loads(result)

    assert parsed["title"] == "Q1 Report"
    assert len(parsed["segments"]) == 1
    assert parsed["segments"][0]["content"] == "Revenue grew 15%"


@pytest.mark.asyncio
async def test_pam_get_document_not_found(mock_services: PamServices):
    """pam_get_document returns error when document not found."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_get_document

    result = await _pam_get_document(document_title="Nonexistent", source_id=None)
    parsed = json.loads(result)

    assert "error" in parsed


@pytest.mark.asyncio
async def test_pam_list_documents(mock_services: PamServices):
    """pam_list_documents returns paginated document list."""
    mock_doc = MagicMock()
    mock_doc.id = uuid.uuid4()
    mock_doc.title = "Q1 Report"
    mock_doc.source_type = "markdown"
    mock_doc.created_at = datetime(2026, 1, 15, tzinfo=UTC)
    mock_doc.updated_at = datetime(2026, 1, 15, tzinfo=UTC)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_doc]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_list_documents

    result = await _pam_list_documents(limit=10, source_type=None)
    parsed = json.loads(result)

    assert len(parsed["documents"]) == 1
    assert parsed["documents"][0]["title"] == "Q1 Report"
