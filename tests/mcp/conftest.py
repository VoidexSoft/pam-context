"""Shared fixtures for MCP tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp.services import PamServices


@pytest.fixture
def mock_services() -> PamServices:
    """Create a PamServices with all dependencies mocked."""
    return PamServices(
        search_service=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=MagicMock(),
        es_client=AsyncMock(),
        graph_service=AsyncMock(),
        vdb_store=AsyncMock(),
        duckdb_service=MagicMock(),
        cache_service=AsyncMock(),
        memory_service=AsyncMock(),
        conversation_service=AsyncMock(),
        glossary_service=AsyncMock(),
    )
