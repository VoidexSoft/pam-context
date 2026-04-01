"""Tests for conversation REST API routes."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from pam.api.deps import get_db
from pam.api.main import create_app
from pam.api.routes.conversation import get_conversation_service
from pam.common.models import ConversationDetail, ConversationResponse, ConvMessageResponse


@pytest.fixture
def mock_conv_service():
    return AsyncMock()


@pytest.fixture
def mock_db_session():
    return AsyncMock()


@pytest.fixture
def app(mock_conv_service, mock_db_session):
    application = create_app()
    application.dependency_overrides[get_conversation_service] = lambda: mock_conv_service
    application.dependency_overrides[get_db] = lambda: mock_db_session
    # Set app.state attributes used by middleware/health that read directly from app.state
    application.state.session_factory = MagicMock()
    application.state.cache_service = None
    application.state.redis_client = None
    application.state.graph_service = None
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_conversation(client, mock_conv_service):
    """POST /api/conversations creates a conversation."""
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.create.return_value = ConversationResponse(
        id=uuid.uuid4(),
        user_id=None,
        project_id=None,
        title="Test",
        started_at=now,
        last_active=now,
        message_count=0,
    )

    resp = await client.post("/api/conversations", json={"title": "Test"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test"


@pytest.mark.asyncio
async def test_get_conversation(client, mock_conv_service):
    """GET /api/conversations/{id} returns conversation detail."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.get.return_value = ConversationDetail(
        id=conv_id,
        title="Chat",
        started_at=now,
        last_active=now,
        message_count=0,
        messages=[],
    )

    resp = await client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Chat"


@pytest.mark.asyncio
async def test_get_conversation_not_found(client, mock_conv_service):
    """GET /api/conversations/{id} returns 404 when not found."""
    mock_conv_service.get.return_value = None
    resp = await client.get(f"/api/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_message(client, mock_conv_service):
    """POST /api/conversations/{id}/messages adds a message."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    # Need to mock get() for ownership check
    mock_conv_service.get.return_value = ConversationDetail(
        id=conv_id, title="Chat", started_at=now, last_active=now,
        message_count=1, messages=[],
    )
    mock_conv_service.add_message.return_value = ConvMessageResponse(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role="user",
        content="Hello",
        metadata={},
        created_at=now,
    )

    resp = await client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "Hello"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Hello"


@pytest.mark.asyncio
async def test_list_conversations(client, mock_conv_service):
    """GET /api/conversations/user/{user_id} lists conversations."""
    user_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.list_by_user.return_value = [
        ConversationResponse(
            id=uuid.uuid4(),
            user_id=user_id,
            title="Chat 1",
            started_at=now,
            last_active=now,
            message_count=5,
        ),
    ]

    resp = await client.get(f"/api/conversations/user/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["message_count"] == 5


@pytest.mark.asyncio
async def test_delete_conversation(client, mock_conv_service):
    """DELETE /api/conversations/{id} deletes conversation."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    # Mock get for ownership check
    mock_conv_service.get.return_value = ConversationDetail(
        id=conv_id, title="Chat", started_at=now, last_active=now,
        message_count=0, messages=[],
    )
    mock_conv_service.delete.return_value = True

    resp = await client.delete(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Conversation deleted"


@pytest.mark.asyncio
async def test_delete_conversation_not_found(client, mock_conv_service):
    """DELETE /api/conversations/{id} returns 404 when not found."""
    mock_conv_service.get.return_value = None
    resp = await client.delete(f"/api/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404
