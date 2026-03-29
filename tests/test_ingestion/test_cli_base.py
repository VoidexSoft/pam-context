"""Tests for CLI connector base class."""

from pam.ingestion.connectors.cli_base import ConnectorError


class TestConnectorError:
    def test_is_exception(self):
        err = ConnectorError("gh not found")
        assert isinstance(err, Exception)

    def test_stores_message(self):
        err = ConnectorError("Run 'gh auth login' first")
        assert str(err) == "Run 'gh auth login' first"

    def test_stores_command(self):
        err = ConnectorError("timeout", command=["gh", "api", "/repos"])
        assert err.command == ["gh", "api", "/repos"]

    def test_command_defaults_to_none(self):
        err = ConnectorError("fail")
        assert err.command is None


import os
from unittest.mock import patch

from pam.common.config import Settings


class TestCliConfigFields:
    def test_github_repos_defaults_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(
                database_url="postgresql+psycopg://x:x@localhost/x",
                openai_api_key="test",
                anthropic_api_key="test",
            )
        assert s.github_repos == []

    def test_github_repos_from_env(self):
        repos_json = '[{"repo":"org/wiki","branch":"main","paths":["docs/"]}]'
        with patch.dict(os.environ, {"GITHUB_REPOS": repos_json}, clear=True):
            s = Settings(
                database_url="postgresql+psycopg://x:x@localhost/x",
                openai_api_key="test",
                anthropic_api_key="test",
            )
        assert len(s.github_repos) == 1
        assert s.github_repos[0]["repo"] == "org/wiki"

    def test_use_cli_connectors_defaults_false(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(
                database_url="postgresql+psycopg://x:x@localhost/x",
                openai_api_key="test",
                anthropic_api_key="test",
            )
        assert s.use_cli_connectors is False

    def test_cli_timeout_defaults_30(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(
                database_url="postgresql+psycopg://x:x@localhost/x",
                openai_api_key="test",
                anthropic_api_key="test",
            )
        assert s.cli_timeout == 30
