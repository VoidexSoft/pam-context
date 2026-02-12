"""Tests for admin routes — user and role management."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.common.models import Project, User, UserProjectRole


class TestListUsers:
    async def test_returns_users(self, client, mock_api_db_session):
        user = User(
            id=uuid.uuid4(),
            email="user@test.com",
            name="Test User",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [user]
        mock_result.scalars.return_value = mock_scalars
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/admin/users")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["email"] == "user@test.com"

    async def test_empty_list(self, client, mock_api_db_session):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/admin/users")
        assert response.status_code == 200
        assert response.json() == []


class TestAssignRole:
    async def test_assign_role_user_not_found(self, client, mock_api_db_session):
        mock_api_db_session.get = AsyncMock(return_value=None)

        response = await client.post(
            "/api/admin/roles",
            json={
                "user_id": str(uuid.uuid4()),
                "project_id": str(uuid.uuid4()),
                "role": "viewer",
            },
        )
        assert response.status_code == 404

    async def test_assign_role_invalid_role(self, client):
        response = await client.post(
            "/api/admin/roles",
            json={
                "user_id": str(uuid.uuid4()),
                "project_id": str(uuid.uuid4()),
                "role": "superadmin",
            },
        )
        assert response.status_code == 422  # Pydantic validation error

    async def test_assign_role_success(self, client, mock_api_db_session):
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()

        user = User(id=user_id, email="u@t.com", name="U")
        project = Project(id=project_id, name="P")

        async def mock_get(cls, id_):
            if cls is User:
                return user
            if cls is Project:
                return project
            return None

        mock_api_db_session.get = mock_get

        # No existing role found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)
        mock_api_db_session.add = MagicMock()

        response = await client.post(
            "/api/admin/roles",
            json={
                "user_id": str(user_id),
                "project_id": str(project_id),
                "role": "editor",
            },
        )
        assert response.status_code == 201
        assert response.json()["role"] == "editor"


class TestDeactivateUser:
    async def test_deactivate_not_found(self, client, mock_api_db_session):
        mock_api_db_session.get = AsyncMock(return_value=None)
        response = await client.patch(f"/api/admin/users/{uuid.uuid4()}/deactivate")
        assert response.status_code == 404

    async def test_deactivate_success(self, client, mock_api_db_session):
        user_id = uuid.uuid4()
        user = User(id=user_id, email="u@t.com", name="U", is_active=True)
        mock_api_db_session.get = AsyncMock(return_value=user)

        response = await client.patch(f"/api/admin/users/{user_id}/deactivate")
        assert response.status_code == 200
        assert user.is_active is False


class TestRoleValidation:
    async def test_viewer_role_accepted(self, client, mock_api_db_session):
        mock_api_db_session.get = AsyncMock(return_value=None)
        response = await client.post(
            "/api/admin/roles",
            json={"user_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "role": "viewer"},
        )
        # Should not fail validation (404 for user not found is expected)
        assert response.status_code != 422

    async def test_editor_role_accepted(self, client, mock_api_db_session):
        mock_api_db_session.get = AsyncMock(return_value=None)
        response = await client.post(
            "/api/admin/roles",
            json={"user_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "role": "editor"},
        )
        assert response.status_code != 422

    async def test_admin_role_accepted(self, client, mock_api_db_session):
        mock_api_db_session.get = AsyncMock(return_value=None)
        response = await client.post(
            "/api/admin/roles",
            json={"user_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "role": "admin"},
        )
        assert response.status_code != 422
