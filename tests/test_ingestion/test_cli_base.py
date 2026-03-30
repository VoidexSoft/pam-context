"""Tests for CLI connector base class."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.common.config import Settings
from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector, ConnectorError


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


# ---------------------------------------------------------------------------
# Task 2: CliConnector ABC tests
# ---------------------------------------------------------------------------


class ConcreteCliConnector(CliConnector):
    """Minimal concrete subclass for testing the ABC."""

    cli_binary = "testcli"

    async def list_documents(self) -> list[DocumentInfo]:
        return []

    async def fetch_document(self, source_id: str) -> RawDocument:
        raise NotImplementedError

    async def get_content_hash(self, source_id: str) -> str:
        raise NotImplementedError


def _make_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Create a mock asyncio.subprocess.Process."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


class TestCheckAvailable:
    async def test_returns_true_when_cli_exists(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=0, stdout=b"testcli version 1.0\n")
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await connector.check_available()
        assert result is True
        mock_exec.assert_called_once()

    async def test_returns_false_when_cli_missing(self):
        connector = ConcreteCliConnector()
        with patch(
            "pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("No such file"),
        ):
            result = await connector.check_available()
        assert result is False


class TestRunCli:
    async def test_parses_json_stdout(self):
        connector = ConcreteCliConnector()
        payload = {"tree": [{"path": "README.md"}]}
        proc = _make_process(stdout=json.dumps(payload).encode())
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc):
            result = await connector.run_cli(["api", "/repos/owner/repo"])
        assert result == payload

    async def test_raises_on_nonzero_exit(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=1, stderr=b"not found")
        with (
            patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ConnectorError, match="not found"),
        ):
            await connector.run_cli(["api", "/bad"])

    async def test_raises_on_auth_error(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=1, stderr=b"error: auth required")
        with (
            patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ConnectorError, match="auth"),
        ):
            await connector.run_cli(["api", "/repos"])

    async def test_raises_on_timeout(self):
        connector = ConcreteCliConnector()

        async def slow_communicate():
            raise TimeoutError()

        proc = AsyncMock()
        proc.communicate = slow_communicate
        proc.kill = MagicMock()
        proc.returncode = None
        with (
            patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ConnectorError, match="timed out"),
        ):
            await connector.run_cli(["api", "/slow"], timeout=1)

    async def test_retries_on_rate_limit(self):
        connector = ConcreteCliConnector()
        rate_limit_proc = _make_process(returncode=1, stderr=b"rate limit exceeded")
        ok_proc = _make_process(stdout=b'{"ok": true}')

        call_count = 0

        async def create_proc(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return rate_limit_proc
            return ok_proc

        with (
            patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", side_effect=create_proc),
            patch("pam.ingestion.connectors.cli_base.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await connector.run_cli(["api", "/repos"])
        assert result == {"ok": True}
        assert call_count == 2


class TestRunCliRaw:
    async def test_returns_raw_bytes(self):
        connector = ConcreteCliConnector()
        raw = b"# Hello World\n\nSome markdown content."
        proc = _make_process(stdout=raw)
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc):
            result = await connector.run_cli_raw(["api", "/repos/o/r/contents/f"])
        assert result == raw

    async def test_raises_on_nonzero_exit(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=1, stderr=b"404 Not Found")
        with (
            patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ConnectorError, match="Not Found"),
        ):
            await connector.run_cli_raw(["api", "/bad"])
