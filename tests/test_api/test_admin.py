"""Tests for admin routes — user and role management."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from pam.common.models import Project, User


class TestGetUser:
    def _make_mock_user(self, user_id, email="detail@test.com", name="Detail User", roles=None):
        """Helper: create a mock user that behaves like a SQLAlchemy ORM User."""
        now = datetime.now(UTC)
        user = MagicMock()
        user.id = user_id
        user.email = email
        user.name = name
        user.is_active = True
        user.picture = None
        user.google_id = None
        user.created_at = now
        user.updated_at = now
        user.project_roles = roles or []
        return user

    async def test_get_user_found(self, client, mock_api_db_session):
        """GET /admin/users/{user_id} returns user with roles."""
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()

        role = MagicMock()
        role.project_id = project_id
        role.project = MagicMock()
        role.project.name = "Test Project"
        role.role = "editor"

        user = self._make_mock_user(user_id, roles=[role])

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get(f"/api/admin/users/{user_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "detail@test.com"
        assert data["name"] == "Detail User"
        assert len(data["roles"]) == 1
        assert data["roles"][0]["project_name"] == "Test Project"
        assert data["roles"][0]["role"] == "editor"

    async def test_get_user_not_found(self, client, mock_api_db_session):
        """GET /admin/users/{user_id} returns 404 for unknown user."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get(f"/api/admin/users/{uuid.uuid4()}")
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    async def test_get_user_no_roles(self, client, mock_api_db_session):
        """GET /admin/users/{user_id} returns empty roles list for user without roles."""
        user_id = uuid.uuid4()
        user = self._make_mock_user(user_id, email="noroles@test.com", name="No Roles", roles=[])

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.get(f"/api/admin/users/{user_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["roles"] == []


class TestListUsers:
    async def test_returns_users(self, client, mock_api_db_session):
        user = User(
            id=uuid.uuid4(),
            email="user@test.com",
            name="Test User",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        # First call: count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        # Second call: users query
        user_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [user]
        user_result.scalars.return_value = mock_scalars

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, user_result])

        response = await client.get("/api/admin/users")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["email"] == "user@test.com"

    async def test_empty_list(self, client, mock_api_db_session):
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        user_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        user_result.scalars.return_value = mock_scalars

        mock_api_db_session.execute = AsyncMock(side_effect=[count_result, user_result])

        response = await client.get("/api/admin/users")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0


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
