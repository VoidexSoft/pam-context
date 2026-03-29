"""Tests for MCP resources."""

from __future__ import annotations

import json
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
async def test_pam_stats_resource(mock_services: PamServices):
    """pam://stats returns system statistics."""
    mock_services.es_client.count = AsyncMock(return_value={"count": 150})

    mock_session = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 25
    mock_session.execute = AsyncMock(return_value=mock_count_result)
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _get_stats

    result = await _get_stats()
    parsed = json.loads(result)

    assert "document_count" in parsed
    assert "segment_count" in parsed


@pytest.mark.asyncio
async def test_pam_entities_resource(mock_services: PamServices):
    """pam://entities returns entity listing."""
    mock_services.es_client.search = AsyncMock(
        return_value={
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "name": "AuthService",
                            "type": "service",
                            "description": "Handles authentication",
                        }
                    }
                ],
                "total": {"value": 1},
            }
        }
    )

    from pam.mcp.server import _get_entities

    result = await _get_entities(entity_type="service")
    parsed = json.loads(result)

    assert len(parsed["entities"]) == 1
    assert parsed["entities"][0]["name"] == "AuthService"
