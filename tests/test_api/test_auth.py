"""Tests for JWT auth, token creation/validation, and auth dependencies."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from fastapi import HTTPException

from pam.api.auth import (
    create_access_token,
    decode_access_token,
    get_current_user,
    get_user_project_ids,
    require_admin,
    require_auth,
)
from pam.common.config import settings
from pam.common.models import User


class TestCreateAccessToken:
    def test_creates_valid_token(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "test@example.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_claims(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "test@example.com")
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "test@example.com"
        assert "exp" in payload
        assert "iat" in payload

    def test_token_expiry(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "test@example.com")
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        assert (exp - iat).total_seconds() == settings.jwt_expiry_hours * 3600


class TestDecodeAccessToken:
    def test_decode_valid_token(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "test@example.com")
        payload = decode_access_token(token)
        assert payload["sub"] == str(user_id)

    def test_decode_expired_token(self):
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "test@example.com",
            "iat": datetime.now(timezone.utc) - timedelta(hours=48),
            "exp": datetime.now(timezone.utc) - timedelta(hours=24),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_decode_invalid_token(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("invalid.token.here")
        assert exc_info.value.status_code == 401

    def test_decode_wrong_secret(self):
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "test@example.com",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        token = jwt.encode(payload, "wrong-secret-at-least-32-bytes!!", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401


class TestGetUserProjectIds:
    def test_returns_none_when_no_user(self):
        result = get_user_project_ids(None)
        assert result is None

    def test_returns_project_ids(self):
        user = MagicMock()
        pid1 = uuid.uuid4()
        pid2 = uuid.uuid4()
        role1 = MagicMock()
        role1.project_id = pid1
        role2 = MagicMock()
        role2.project_id = pid2
        user.project_roles = [role1, role2]

        result = get_user_project_ids(user)
        assert result == [pid1, pid2]

    def test_returns_empty_for_no_roles(self):
        user = MagicMock()
        user.project_roles = []
        result = get_user_project_ids(user)
        assert result == []


class TestDevLoginEndpoint:
    async def test_dev_login_creates_user(self, client, mock_api_db_session):
        """Dev login should work when auth_required=False."""
        from pam.common.models import User

        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Mock: no existing user found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)
        mock_api_db_session.add = MagicMock()

        # Mock refresh to populate the user object
        async def mock_refresh(obj):
            obj.id = user_id
            obj.created_at = now
            obj.updated_at = now
            obj.is_active = True
            obj.picture = None
            obj.google_id = None

        mock_api_db_session.refresh = mock_refresh

        response = await client.post("/api/auth/dev-login", json={"email": "dev@test.com"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "dev@test.com"

    async def test_dev_login_existing_user(self, client, mock_api_db_session):
        """Dev login with existing user should return token."""
        from pam.common.models import User

        user = User(
            id=uuid.uuid4(),
            email="dev@test.com",
            name="Dev User",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        response = await client.post("/api/auth/dev-login", json={"email": "dev@test.com"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    async def test_dev_login_blocked_in_production(self, client):
        """Dev login should be blocked when auth_required=True."""
        with patch.object(settings, "auth_required", True):
            response = await client.post("/api/auth/dev-login", json={"email": "dev@test.com"})
            assert response.status_code == 403


class TestGetCurrentUser:
    """Tests for the get_current_user dependency."""

    async def test_returns_none_when_auth_disabled(self):
        """When auth_required=False, get_current_user returns None."""
        with patch.object(settings, "auth_required", False):
            result = await get_current_user(db=AsyncMock(), credentials=None)
            assert result is None

    async def test_returns_user_with_valid_token(self, mock_api_db_session):
        """Valid Bearer token resolves to the corresponding user."""
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="test@example.com",
            name="Test",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        user.project_roles = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        token = create_access_token(user_id, "test@example.com")
        creds = MagicMock()
        creds.credentials = token

        with patch.object(settings, "auth_required", True):
            result = await get_current_user(db=mock_api_db_session, credentials=creds)
            assert result is not None
            assert result.email == "test@example.com"

    async def test_raises_401_when_no_token_and_auth_required(self):
        """Missing token raises 401 when auth is required."""
        with patch.object(settings, "auth_required", True):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(db=AsyncMock(), credentials=None)
            assert exc_info.value.status_code == 401

    async def test_raises_401_for_expired_token(self):
        """Expired token raises 401."""
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "test@example.com",
            "iat": datetime.now(timezone.utc) - timedelta(hours=48),
            "exp": datetime.now(timezone.utc) - timedelta(hours=24),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        creds = MagicMock()
        creds.credentials = token

        with patch.object(settings, "auth_required", True):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(db=AsyncMock(), credentials=creds)
            assert exc_info.value.status_code == 401

    async def test_raises_401_for_inactive_user(self, mock_api_db_session):
        """Inactive user raises 401 even with valid token."""
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="inactive@example.com",
            name="Inactive",
            is_active=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        user.project_roles = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        token = create_access_token(user_id, "inactive@example.com")
        creds = MagicMock()
        creds.credentials = token

        with patch.object(settings, "auth_required", True):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(db=mock_api_db_session, credentials=creds)
            assert exc_info.value.status_code == 401


class TestRequireAuth:
    """Tests for the require_auth dependency."""

    async def test_raises_401_when_user_is_none_and_auth_enabled(self):
        """When auth is enabled and user is None, raises 401."""
        with patch.object(settings, "auth_required", True):
            with pytest.raises(HTTPException) as exc_info:
                await require_auth(user=None)
            assert exc_info.value.status_code == 401

    async def test_returns_user_when_valid(self):
        """Valid user is passed through."""
        user = MagicMock(spec=User)
        with patch.object(settings, "auth_required", True):
            result = await require_auth(user=user)
            assert result is user

    async def test_raises_403_when_auth_disabled_and_none(self):
        """When auth is disabled, require_auth with None raises 403 (safety guard)."""
        with patch.object(settings, "auth_required", False):
            with pytest.raises(HTTPException) as exc_info:
                await require_auth(user=None)
            assert exc_info.value.status_code == 403


class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    async def test_returns_none_when_auth_disabled(self):
        """When auth is disabled, require_admin returns None."""
        with patch.object(settings, "auth_required", False):
            result = await require_admin(user=None)
            assert result is None

    async def test_raises_401_when_no_user_and_auth_enabled(self):
        """When auth is enabled and no user, raises 401."""
        with patch.object(settings, "auth_required", True):
            with pytest.raises(HTTPException) as exc_info:
                await require_admin(user=None)
            assert exc_info.value.status_code == 401

    async def test_raises_403_for_non_admin_user(self):
        """User without admin role gets 403."""
        user = MagicMock(spec=User)
        role = MagicMock()
        role.role = "viewer"
        user.project_roles = [role]
        with patch.object(settings, "auth_required", True):
            with pytest.raises(HTTPException) as exc_info:
                await require_admin(user=user)
            assert exc_info.value.status_code == 403

    async def test_passes_for_admin_user(self):
        """User with admin role passes through."""
        user = MagicMock(spec=User)
        role = MagicMock()
        role.role = "admin"
        user.project_roles = [role]
        with patch.object(settings, "auth_required", True):
            result = await require_admin(user=user)
            assert result is user


class TestAuthMeEndpoint:
    """Tests for the /auth/me endpoint."""

    async def test_returns_404_when_auth_disabled(self, client):
        """When auth_required=False, /auth/me returns 404."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 404

    async def test_returns_user_when_authenticated(self, client, app, mock_api_db_session):
        """With auth enabled and valid token, /auth/me returns user profile."""
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        user = User(
            id=user_id,
            email="me@example.com",
            name="Me",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        user.project_roles = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)

        token = create_access_token(user_id, "me@example.com")

        with patch.object(settings, "auth_required", True):
            response = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["email"] == "me@example.com"

    async def test_returns_401_without_token_when_auth_enabled(self, client):
        """With auth enabled and no token, /auth/me returns 401."""
        with patch.object(settings, "auth_required", True):
            response = await client.get("/api/auth/me")
            assert response.status_code == 401


class TestAuthDisabledByDefault:
    """When auth_required=False (default), all endpoints should be accessible."""

    async def test_chat_accessible_without_token(self, client):
        response = await client.post("/api/chat", json={"message": "hello"})
        assert response.status_code != 401
        assert response.status_code != 403

    async def test_search_accessible_without_token(self, client):
        response = await client.post("/api/search", json={"query": "test"})
        assert response.status_code != 401
        assert response.status_code != 403

    async def test_documents_accessible_without_token(self, client, mock_api_db_session):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)
        response = await client.get("/api/documents")
        assert response.status_code != 401
        assert response.status_code != 403

    async def test_stats_accessible_without_token(self, client, mock_api_db_session):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_api_db_session.execute = AsyncMock(return_value=mock_result)
        response = await client.get("/api/stats")
        assert response.status_code != 401
        assert response.status_code != 403


class TestAuthEnforcedWhenEnabled:
    """When auth_required=True, endpoints must reject unauthenticated requests."""

    async def test_chat_requires_auth(self, client):
        with patch.object(settings, "auth_required", True):
            response = await client.post("/api/chat", json={"message": "hello"})
            assert response.status_code == 401

    async def test_chat_stream_requires_auth(self, client):
        with patch.object(settings, "auth_required", True):
            response = await client.post("/api/chat/stream", json={"message": "hello"})
            assert response.status_code == 401

    async def test_search_requires_auth(self, client):
        with patch.object(settings, "auth_required", True):
            response = await client.post("/api/search", json={"query": "test"})
            assert response.status_code == 401

    async def test_documents_requires_auth(self, client):
        with patch.object(settings, "auth_required", True):
            response = await client.get("/api/documents")
            assert response.status_code == 401

    async def test_segments_requires_auth(self, client):
        with patch.object(settings, "auth_required", True):
            response = await client.get(f"/api/segments/{uuid.uuid4()}")
            assert response.status_code == 401

    async def test_stats_requires_auth(self, client):
        with patch.object(settings, "auth_required", True):
            response = await client.get("/api/stats")
            assert response.status_code == 401
