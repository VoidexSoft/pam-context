"""Tests for JWT auth, token creation/validation, and auth dependencies."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from pam.api.auth import create_access_token, decode_access_token, get_user_project_ids
from pam.common.config import settings


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
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_decode_invalid_token(self):
        from fastapi import HTTPException

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
        from fastapi import HTTPException

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
