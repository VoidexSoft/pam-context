"""Tests for pam.common.config — Settings defaults and overrides."""

import os
from unittest.mock import patch

from pam.common.config import Settings


class TestSettings:
    def test_default_values(self):
        """Settings should have sensible defaults."""
        s = Settings(
            _env_file=None,
            openai_api_key="test",
            anthropic_api_key="test",
        )
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
