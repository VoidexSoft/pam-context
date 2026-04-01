"""Tests for MCP memory tools."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from pam.common.models import MemoryResponse, MemorySearchResult
from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_remember_stores_fact(mock_services: PamServices):
    """pam_remember calls memory_service.store and returns JSON."""
    memory_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    mock_services.memory_service.store = AsyncMock(
        return_value=MemoryResponse(
            id=memory_id,
            type="fact",
            content="Revenue target is $10M",
            importance=0.5,
            access_count=0,
            created_at=now,
            updated_at=now,
        )
    )

    from pam.mcp.server import _pam_remember

    result = await _pam_remember(
        content="Revenue target is $10M",
        memory_type="fact",
        source="manual",
    )
    parsed = json.loads(result)

    assert parsed["content"] == "Revenue target is $10M"
    assert parsed["type"] == "fact"
    assert "id" in parsed
    mock_services.memory_service.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_recall_returns_scored_results(mock_services: PamServices):
    """pam_recall calls memory_service.search and returns JSON."""
    memory_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    mock_services.memory_service.search = AsyncMock(
        return_value=[
            MemorySearchResult(
                memory=MemoryResponse(
                    id=memory_id,
                    type="fact",
                    content="Revenue target is $10M",
                    importance=0.7,
                    access_count=3,
                    created_at=now,
                    updated_at=now,
                ),
                score=0.92,
            )
        ]
    )

    from pam.mcp.server import _pam_recall

    result = await _pam_recall(query="revenue targets", top_k=5)
    parsed = json.loads(result)

    assert len(parsed["memories"]) == 1
    assert parsed["memories"][0]["content"] == "Revenue target is $10M"
    assert parsed["memories"][0]["score"] == 0.92
    mock_services.memory_service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_recall_empty_results(mock_services: PamServices):
    """pam_recall returns empty list when no memories match."""
    mock_services.memory_service.search = AsyncMock(return_value=[])

    from pam.mcp.server import _pam_recall

    result = await _pam_recall(query="nonexistent topic", top_k=5)
    parsed = json.loads(result)

    assert parsed["memories"] == []
    assert parsed["count"] == 0


@pytest.mark.asyncio
async def test_pam_forget_deletes_memory(mock_services: PamServices):
    """pam_forget calls memory_service.delete and returns status."""
    user_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    mock_services.memory_service.get_for_ownership_check = AsyncMock(
        return_value=MemoryResponse(
            id=memory_id, type="fact", content="x", importance=0.5,
            access_count=0, user_id=user_id,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
    )
    mock_services.memory_service.delete = AsyncMock(return_value=True)

    from pam.mcp.server import _pam_forget

    result = await _pam_forget(memory_id=str(memory_id), user_id=str(user_id))
    parsed = json.loads(result)

    assert parsed["deleted"] is True
    assert parsed["memory_id"] == str(memory_id)


@pytest.mark.asyncio
async def test_pam_forget_not_found(mock_services: PamServices):
    """pam_forget returns error when memory doesn't exist."""
    mock_services.memory_service.get_for_ownership_check = AsyncMock(return_value=None)

    from pam.mcp.server import _pam_forget

    memory_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    result = await _pam_forget(memory_id=memory_id, user_id=user_id)
    parsed = json.loads(result)

    assert parsed["deleted"] is False
    assert "error" in parsed


@pytest.mark.asyncio
async def test_pam_forget_rejects_wrong_owner(mock_services: PamServices):
    """pam_forget rejects deletion when user_id doesn't match memory owner."""
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    mock_services.memory_service.get_for_ownership_check = AsyncMock(
        return_value=MemoryResponse(
            id=memory_id, type="fact", content="x", importance=0.5,
            access_count=0, user_id=owner_id,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
    )

    from pam.mcp.server import _pam_forget

    result = await _pam_forget(memory_id=str(memory_id), user_id=str(other_user_id))
    parsed = json.loads(result)

    assert parsed["deleted"] is False
    assert "error" in parsed
    mock_services.memory_service.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_pam_remember_unavailable_when_no_service(mock_services: PamServices):
    """pam_remember returns error when memory_service is None."""
    mock_services.memory_service = None
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_remember

    result = await _pam_remember(content="test", memory_type="fact")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "unavailable" in parsed["error"].lower()
