"""Tests for pam.common.config — Settings defaults and overrides."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from pam.common.config import Settings, get_settings, reset_settings


class TestSettings:
    @patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "test",
            "ANTHROPIC_API_KEY": "test",
        },
        clear=True,
    )
    def test_default_values(self):
        """Settings should have sensible defaults."""
        s = Settings(_env_file=None)
        assert s.database_url == "postgresql+psycopg://pam:pam@localhost:5432/pam_context"
        assert s.elasticsearch_url == "http://localhost:9200"
        assert s.elasticsearch_index == "pam_segments"
        assert s.embedding_model == "text-embedding-3-large"
        assert s.embedding_dims == 1536
        assert s.agent_model == "claude-sonnet-4-5-20250514"
        assert s.chunk_size_tokens == 512
        assert s.log_level == "INFO"
        assert s.cors_origins == ["http://localhost:5173"]

    def test_env_override(self):
        """Settings should be overridable via environment variables."""
        env = {
            "DATABASE_URL": "postgresql+psycopg://other:other@db:5432/other",
            "ELASTICSEARCH_URL": "http://es:9200",
            "ELASTICSEARCH_INDEX": "custom_index",
            "EMBEDDING_DIMS": "768",
            "CHUNK_SIZE_TOKENS": "256",
            "LOG_LEVEL": "DEBUG",
            "OPENAI_API_KEY": "sk-test",
            "ANTHROPIC_API_KEY": "ant-test",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)
            assert s.database_url == "postgresql+psycopg://other:other@db:5432/other"
            assert s.elasticsearch_url == "http://es:9200"
            assert s.elasticsearch_index == "custom_index"
            assert s.embedding_dims == 768
            assert s.chunk_size_tokens == 256
            assert s.log_level == "DEBUG"
            assert s.openai_api_key == "sk-test"

    def test_cors_origins_list(self):
        """CORS origins should accept a JSON list from env."""
        env = {
            "CORS_ORIGINS": '["http://localhost:3000","http://localhost:5173"]',
            "OPENAI_API_KEY": "test",
            "ANTHROPIC_API_KEY": "test",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)
            assert "http://localhost:3000" in s.cors_origins


class TestJwtSecretValidation:
    def test_insecure_secret_with_auth_required_raises(self):
        """Should raise at construction if auth_required=True and JWT secret is insecure."""
        with pytest.raises(ValidationError, match="Insecure JWT secret"):
            Settings(
                _env_file=None,
                auth_required=True,
                jwt_secret="dev-secret-change-in-production-32b",
            )

    def test_insecure_secret_without_auth_is_ok(self):
        """Should not raise if auth_required=False even with insecure secret."""
        s = Settings(
            _env_file=None,
            auth_required=False,
            jwt_secret="dev-secret-change-in-production-32b",
        )
        assert s.jwt_secret == "dev-secret-change-in-production-32b"  # noqa: S105

    def test_secure_secret_with_auth_is_ok(self):
        """Should not raise if JWT secret is a custom strong value."""
        s = Settings(
            _env_file=None,
            auth_required=True,
            jwt_secret="a-very-strong-and-unique-secret-key-1234567890",
        )
        assert s.auth_required is True

    def test_short_secret_with_auth_required_raises(self):
        """Should raise at construction if auth_required=True and JWT secret < 32 chars."""
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(
                _env_file=None,
                auth_required=True,
                jwt_secret="too-short-secret",
            )

    def test_other_insecure_defaults_also_blocked(self):
        """Other known-insecure secrets should also be rejected at construction."""
        for secret in ("secret", "changeme", "password"):
            with pytest.raises(ValidationError, match="Insecure JWT secret"):
                Settings(_env_file=None, auth_required=True, jwt_secret=secret)


class TestGetSettings:
    def test_get_settings_returns_settings_instance(self):
        """get_settings() should return a Settings instance."""
        reset_settings()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_is_cached(self):
        """Repeated calls to get_settings() should return the same object."""
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_settings_clears_cache(self):
        """reset_settings() should cause a new Settings instance to be created."""
        reset_settings()
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2
