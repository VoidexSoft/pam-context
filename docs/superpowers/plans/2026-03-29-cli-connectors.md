# CLI-First Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CLI-first connectors (GitHub via `gh`, Google Workspace via `gws`) to the ingestion pipeline with new API endpoints for ad-hoc and multi-source sync.

**Architecture:** New abstract `CliConnector` base provides subprocess + JSON plumbing on top of existing `BaseConnector` ABC. Three concrete implementations (`GitHubConnector`, `GwsDocsConnector`, `GwsSheetsConnector`) wrap their respective CLIs. A factory function selects between old Google API connectors and new GWS CLI connectors based on config. Two new API endpoints (`POST /ingest/github`, `POST /ingest/sync`) reuse the existing task manager pattern.

**Tech Stack:** Python 3.12, asyncio subprocess, FastAPI, Pydantic Settings, pytest + AsyncMock, structlog

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/pam/ingestion/connectors/cli_base.py` | `ConnectorError` exception + `CliConnector` ABC with subprocess helpers |
| Create | `src/pam/ingestion/connectors/github.py` | `GitHubConnector` — list/fetch/hash via `gh api` |
| Create | `src/pam/ingestion/connectors/gws_docs.py` | `GwsDocsConnector` — list/fetch/hash via `gws` CLI |
| Create | `src/pam/ingestion/connectors/gws_sheets.py` | `GwsSheetsConnector` — list/fetch/hash via `gws` CLI |
| Create | `src/pam/ingestion/connectors/factory.py` | `get_google_docs_connector()`, `get_google_sheets_connector()` factory functions |
| Modify | `src/pam/common/config.py` | Add `github_repos`, `use_cli_connectors`, `cli_timeout` settings |
| Modify | `src/pam/ingestion/connectors/__init__.py` | Export all connectors and factory functions |
| Modify | `src/pam/ingestion/task_manager.py` | Add `spawn_github_ingestion_task()` and `spawn_sync_task()` |
| Modify | `src/pam/api/routes/ingest.py` | Add `POST /ingest/github` and `POST /ingest/sync` endpoints |
| Create | `tests/test_ingestion/test_cli_base.py` | Unit tests for `CliConnector` base class |
| Create | `tests/test_ingestion/test_github_connector.py` | Unit tests for `GitHubConnector` |
| Create | `tests/test_ingestion/test_gws_docs_connector.py` | Unit tests for `GwsDocsConnector` |
| Create | `tests/test_ingestion/test_gws_sheets_connector.py` | Unit tests for `GwsSheetsConnector` |
| Create | `tests/test_ingestion/test_connector_factory.py` | Unit tests for factory toggle |
| Create | `tests/test_ingestion/test_ingest_api_github.py` | Unit tests for new API endpoints |
| Create | `tests/integration/test_github_integration.py` | Integration test (requires `gh auth`) |

---

### Task 1: ConnectorError and Config Settings

**Files:**
- Create: `src/pam/ingestion/connectors/cli_base.py` (just the error class for now)
- Modify: `src/pam/common/config.py`
- Create: `tests/test_ingestion/test_cli_base.py` (error + config tests)

- [ ] **Step 1: Write failing test for ConnectorError**

```python
# tests/test_ingestion/test_cli_base.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py::TestConnectorError -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pam.ingestion.connectors.cli_base'`

- [ ] **Step 3: Implement ConnectorError**

```python
# src/pam/ingestion/connectors/cli_base.py
"""Base class for CLI-backed connectors (gh, gws)."""

from __future__ import annotations


class ConnectorError(Exception):
    """Raised when a CLI connector encounters an error."""

    def __init__(self, message: str, *, command: list[str] | None = None) -> None:
        super().__init__(message)
        self.command = command
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py::TestConnectorError -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Write failing test for new config fields**

Add to `tests/test_ingestion/test_cli_base.py`:

```python
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
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py::TestCliConfigFields -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'github_repos'`

- [ ] **Step 7: Add config fields to Settings**

Edit `src/pam/common/config.py` — add these three fields after the existing `ingest_root` line (line 92):

```python
    # CLI connectors
    github_repos: list[dict] = []  # [{"repo":"owner/repo","branch":"main","paths":[],"extensions":[]}]
    use_cli_connectors: bool = False  # Use gws CLI instead of Google API connectors
    cli_timeout: int = 30  # Seconds per CLI subprocess call
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py -v`
Expected: All 8 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/pam/ingestion/connectors/cli_base.py src/pam/common/config.py tests/test_ingestion/test_cli_base.py
git commit -m "feat: add ConnectorError and CLI config fields"
```

---

### Task 2: CliConnector Base Class — Subprocess Helpers

**Files:**
- Modify: `src/pam/ingestion/connectors/cli_base.py`
- Modify: `tests/test_ingestion/test_cli_base.py`

- [ ] **Step 1: Write failing tests for check_available()**

Add to `tests/test_ingestion/test_cli_base.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pam.ingestion.connectors.cli_base import CliConnector, ConnectorError
from pam.common.models import DocumentInfo, RawDocument


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
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc) as mock_exec:
            result = await connector.check_available()
        assert result is True
        mock_exec.assert_called_once()

    async def test_returns_false_when_cli_missing(self):
        connector = ConcreteCliConnector()
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    side_effect=FileNotFoundError("No such file")):
            result = await connector.check_available()
        assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py::TestCheckAvailable -v`
Expected: FAIL — `ImportError: cannot import name 'CliConnector'`

- [ ] **Step 3: Write failing tests for run_cli()**

Add to `tests/test_ingestion/test_cli_base.py`:

```python
import json


class TestRunCli:
    async def test_parses_json_stdout(self):
        connector = ConcreteCliConnector()
        payload = {"tree": [{"path": "README.md"}]}
        proc = _make_process(stdout=json.dumps(payload).encode())
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc):
            result = await connector.run_cli(["api", "/repos/owner/repo"])
        assert result == payload

    async def test_raises_on_nonzero_exit(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=1, stderr=b"not found")
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc):
            with pytest.raises(ConnectorError, match="not found"):
                await connector.run_cli(["api", "/bad"])

    async def test_raises_on_auth_error(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=1, stderr=b"error: auth required")
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc):
            with pytest.raises(ConnectorError, match="auth"):
                await connector.run_cli(["api", "/repos"])

    async def test_raises_on_timeout(self):
        connector = ConcreteCliConnector()

        async def slow_communicate():
            raise asyncio.TimeoutError()

        proc = AsyncMock()
        proc.communicate = slow_communicate
        proc.kill = MagicMock()
        proc.returncode = None
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc):
            with pytest.raises(ConnectorError, match="timed out"):
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

        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    side_effect=create_proc):
            with patch("pam.ingestion.connectors.cli_base.asyncio.sleep", new_callable=AsyncMock):
                result = await connector.run_cli(["api", "/repos"])
        assert result == {"ok": True}
        assert call_count == 2
```

- [ ] **Step 4: Write failing tests for run_cli_raw()**

Add to `tests/test_ingestion/test_cli_base.py`:

```python
class TestRunCliRaw:
    async def test_returns_raw_bytes(self):
        connector = ConcreteCliConnector()
        raw = b"# Hello World\n\nSome markdown content."
        proc = _make_process(stdout=raw)
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc):
            result = await connector.run_cli_raw(["api", "/repos/o/r/contents/f"])
        assert result == raw

    async def test_raises_on_nonzero_exit(self):
        connector = ConcreteCliConnector()
        proc = _make_process(returncode=1, stderr=b"404 Not Found")
        with patch("pam.ingestion.connectors.cli_base.asyncio.create_subprocess_exec",
                    return_value=proc):
            with pytest.raises(ConnectorError, match="Not Found"):
                await connector.run_cli_raw(["api", "/bad"])
```

- [ ] **Step 5: Run all new tests to verify they fail**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py -k "not TestConnectorError and not TestCliConfigFields" -v`
Expected: FAIL — `ImportError: cannot import name 'CliConnector'`

- [ ] **Step 6: Implement CliConnector base class**

Replace `src/pam/ingestion/connectors/cli_base.py` with:

```python
"""Base class for CLI-backed connectors (gh, gws)."""

from __future__ import annotations

import asyncio
import json
from abc import ABC

import structlog

from pam.common.config import settings
from pam.ingestion.connectors.base import BaseConnector

logger = structlog.get_logger()

_RATE_LIMIT_KEYWORDS = ("rate limit", "rate_limit", "secondary rate", "abuse detection")
_AUTH_KEYWORDS = ("auth", "login", "credentials", "token")
_MAX_RETRIES = 3
_BACKOFF_BASE = 5  # seconds: 5, 15, 45


class ConnectorError(Exception):
    """Raised when a CLI connector encounters an error."""

    def __init__(self, message: str, *, command: list[str] | None = None) -> None:
        super().__init__(message)
        self.command = command


class CliConnector(BaseConnector, ABC):
    """Abstract base for connectors that shell out to CLI tools."""

    cli_binary: str  # Subclass must set: "gh" or "gws"

    async def check_available(self) -> bool:
        """Verify the CLI binary is installed and reachable."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_binary, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def run_cli(
        self, args: list[str], *, timeout: int | None = None,
    ) -> dict | list:
        """Run CLI command, parse JSON stdout, raise ConnectorError on failure.

        Retries up to 3 times on rate limit errors with exponential backoff.
        """
        timeout = timeout or settings.cli_timeout
        full_cmd = [self.cli_binary, *args]

        for attempt in range(_MAX_RETRIES):
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(timeout):
                    stdout, stderr = await proc.communicate()
            except (asyncio.TimeoutError, TimeoutError):
                proc.kill()
                raise ConnectorError(
                    f"Command timed out after {timeout}s: {' '.join(full_cmd)}",
                    command=full_cmd,
                )

            stderr_text = stderr.decode(errors="replace").strip()

            if proc.returncode == 0:
                logger.info(
                    "cli_run",
                    binary=self.cli_binary,
                    args=args,
                    exit_code=0,
                )
                return json.loads(stdout)

            # Check rate limit — retry with backoff
            stderr_lower = stderr_text.lower()
            if any(kw in stderr_lower for kw in _RATE_LIMIT_KEYWORDS):
                if attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE * (3 ** attempt)  # 5, 15, 45
                    logger.warning(
                        "cli_rate_limited",
                        binary=self.cli_binary,
                        attempt=attempt + 1,
                        retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    continue

            # Check auth error — don't retry
            if any(kw in stderr_lower for kw in _AUTH_KEYWORDS):
                raise ConnectorError(
                    f"Run '{self.cli_binary} auth login' first: {stderr_text}",
                    command=full_cmd,
                )

            # Generic failure
            logger.error(
                "cli_run_failed",
                binary=self.cli_binary,
                args=args,
                exit_code=proc.returncode,
                stderr=stderr_text,
            )
            raise ConnectorError(stderr_text or f"CLI exited with code {proc.returncode}", command=full_cmd)

        # Exhausted retries (only reached on rate limit)
        raise ConnectorError(
            f"Rate limited after {_MAX_RETRIES} retries: {' '.join(full_cmd)}",
            command=full_cmd,
        )

    async def run_cli_raw(
        self, args: list[str], *, timeout: int | None = None,
    ) -> bytes:
        """Run CLI command, return raw stdout bytes (for file content)."""
        timeout = timeout or settings.cli_timeout
        full_cmd = [self.cli_binary, *args]

        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            raise ConnectorError(
                f"Command timed out after {timeout}s: {' '.join(full_cmd)}",
                command=full_cmd,
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace").strip()
            raise ConnectorError(stderr_text or f"CLI exited with code {proc.returncode}", command=full_cmd)

        logger.info(
            "cli_run_raw",
            binary=self.cli_binary,
            args=args,
            bytes_received=len(stdout),
        )
        return stdout
```

- [ ] **Step 7: Run all CliConnector tests to verify they pass**

Run: `python -m pytest tests/test_ingestion/test_cli_base.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/pam/ingestion/connectors/cli_base.py tests/test_ingestion/test_cli_base.py
git commit -m "feat: add CliConnector base with subprocess helpers and retry"
```

---

### Task 3: GitHubConnector — list_documents()

**Files:**
- Create: `src/pam/ingestion/connectors/github.py`
- Create: `tests/test_ingestion/test_github_connector.py`

- [ ] **Step 1: Write failing tests for GitHubConnector.list_documents()**

```python
# tests/test_ingestion/test_github_connector.py
"""Tests for GitHub CLI connector."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.models import DocumentInfo
from pam.ingestion.connectors.github import GitHubConnector


# ── Helpers ──────────────────────────────────────────────────────────

TREE_RESPONSE = {
    "sha": "abc123",
    "tree": [
        {"path": "README.md", "type": "blob", "sha": "sha_readme"},
        {"path": "docs/guide.md", "type": "blob", "sha": "sha_guide"},
        {"path": "docs/api.txt", "type": "blob", "sha": "sha_api"},
        {"path": "src/main.py", "type": "blob", "sha": "sha_main"},
        {"path": "docs/images", "type": "tree", "sha": "sha_dir"},
        {"path": "docs/image.png", "type": "blob", "sha": "sha_png"},
    ],
}


@pytest.fixture
def connector():
    return GitHubConnector(repo="owner/repo", branch="main")


@pytest.fixture
def connector_filtered():
    return GitHubConnector(
        repo="owner/repo",
        branch="develop",
        paths=["docs/"],
        extensions=[".md"],
    )


# ── list_documents tests ────────────────────────────────────────────


class TestListDocuments:
    async def test_returns_md_and_txt_by_default(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector.list_documents()

        source_ids = {d.source_id for d in docs}
        assert source_ids == {
            "owner/repo:README.md",
            "owner/repo:docs/guide.md",
            "owner/repo:docs/api.txt",
        }

    async def test_filters_by_paths_and_extensions(self, connector_filtered):
        with patch.object(connector_filtered, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector_filtered.list_documents()

        source_ids = {d.source_id for d in docs}
        # Only .md files under docs/
        assert source_ids == {"owner/repo:docs/guide.md"}

    async def test_returns_document_info_fields(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector.list_documents()

        guide = next(d for d in docs if "guide" in d.source_id)
        assert isinstance(guide, DocumentInfo)
        assert guide.title == "guide.md"
        assert guide.source_url == "https://github.com/owner/repo/blob/main/docs/guide.md"

    async def test_skips_tree_entries(self, connector):
        """Directories (type=tree) should be excluded."""
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            docs = await connector.list_documents()

        paths = {d.source_id for d in docs}
        assert not any("images" in p for p in paths)

    async def test_empty_tree(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={"tree": []}):
            docs = await connector.list_documents()
        assert docs == []

    async def test_calls_correct_api(self, connector):
        mock_run = AsyncMock(return_value={"tree": []})
        with patch.object(connector, "run_cli", mock_run):
            await connector.list_documents()
        mock_run.assert_called_once_with(
            ["api", "/repos/owner/repo/git/trees/main?recursive=1"]
        )

    async def test_populates_sha_cache(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=TREE_RESPONSE):
            await connector.list_documents()

        assert connector._tree_cache["owner/repo:README.md"] == "sha_readme"
        assert connector._tree_cache["owner/repo:docs/guide.md"] == "sha_guide"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_github_connector.py::TestListDocuments -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pam.ingestion.connectors.github'`

- [ ] **Step 3: Implement GitHubConnector with list_documents()**

```python
# src/pam/ingestion/connectors/github.py
"""GitHub connector — ingests files from GitHub repos via gh CLI."""

from __future__ import annotations

from pathlib import PurePosixPath

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector

logger = structlog.get_logger()


class GitHubConnector(CliConnector):
    """Ingest .md/.txt files from a GitHub repo using the gh CLI."""

    cli_binary = "gh"

    def __init__(
        self,
        repo: str,
        branch: str = "main",
        paths: list[str] | None = None,
        extensions: list[str] | None = None,
    ) -> None:
        self.repo = repo  # "owner/repo" format
        self.branch = branch
        self.paths = paths or []
        self.extensions = extensions or [".md", ".txt"]
        self._tree_cache: dict[str, str] = {}  # source_id -> git SHA

    async def list_documents(self) -> list[DocumentInfo]:
        tree_data = await self.run_cli(
            ["api", f"/repos/{self.repo}/git/trees/{self.branch}?recursive=1"]
        )

        docs: list[DocumentInfo] = []
        for entry in tree_data.get("tree", []):
            if entry.get("type") != "blob":
                continue

            path = entry["path"]
            ext = PurePosixPath(path).suffix.lower()
            if ext not in self.extensions:
                continue

            if self.paths and not any(path.startswith(prefix) for prefix in self.paths):
                continue

            source_id = f"{self.repo}:{path}"
            self._tree_cache[source_id] = entry["sha"]

            docs.append(DocumentInfo(
                source_id=source_id,
                title=PurePosixPath(path).name,
                source_url=f"https://github.com/{self.repo}/blob/{self.branch}/{path}",
            ))

        logger.info("github_list_documents", repo=self.repo, count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        raise NotImplementedError  # Implemented in Task 4

    async def get_content_hash(self, source_id: str) -> str:
        raise NotImplementedError  # Implemented in Task 4
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_github_connector.py::TestListDocuments -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/ingestion/connectors/github.py tests/test_ingestion/test_github_connector.py
git commit -m "feat: add GitHubConnector with list_documents"
```

---

### Task 4: GitHubConnector — fetch_document() and get_content_hash()

**Files:**
- Modify: `src/pam/ingestion/connectors/github.py`
- Modify: `tests/test_ingestion/test_github_connector.py`

- [ ] **Step 1: Write failing tests for get_content_hash()**

Add to `tests/test_ingestion/test_github_connector.py`:

```python
class TestGetContentHash:
    async def test_returns_cached_sha(self, connector):
        connector._tree_cache["owner/repo:README.md"] = "sha_readme"
        result = await connector.get_content_hash("owner/repo:README.md")
        assert result == "sha_readme"

    async def test_raises_when_no_cache(self, connector):
        with pytest.raises(KeyError):
            await connector.get_content_hash("owner/repo:unknown.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_github_connector.py::TestGetContentHash -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Write failing tests for fetch_document()**

Add to `tests/test_ingestion/test_github_connector.py`:

```python
from pam.common.models import RawDocument


class TestFetchDocument:
    async def test_returns_raw_document_for_markdown(self, connector):
        content = b"# Hello World\n\nSome content."
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=content):
            doc = await connector.fetch_document("owner/repo:docs/guide.md")

        assert isinstance(doc, RawDocument)
        assert doc.content == content
        assert doc.content_type == "text/markdown"
        assert doc.source_id == "owner/repo:docs/guide.md"
        assert doc.title == "guide.md"
        assert doc.source_url == "https://github.com/owner/repo/blob/main/docs/guide.md"

    async def test_returns_plain_text_for_txt(self, connector):
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=b"plain text"):
            doc = await connector.fetch_document("owner/repo:notes.txt")

        assert doc.content_type == "text/plain"

    async def test_calls_correct_api_with_raw_accept(self, connector):
        mock_raw = AsyncMock(return_value=b"content")
        with patch.object(connector, "run_cli_raw", mock_raw):
            await connector.fetch_document("owner/repo:docs/guide.md")

        mock_raw.assert_called_once_with([
            "api", "/repos/owner/repo/contents/docs/guide.md?ref=main",
            "-H", "Accept: application/vnd.github.raw+json",
        ])

    async def test_handles_nested_path(self, connector):
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=b"deep"):
            doc = await connector.fetch_document("owner/repo:a/b/c/file.md")

        assert doc.title == "file.md"
        assert "a/b/c/file.md" in doc.source_url
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_github_connector.py::TestFetchDocument -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 5: Implement fetch_document() and get_content_hash()**

Replace the two placeholder methods in `src/pam/ingestion/connectors/github.py`:

```python
    async def fetch_document(self, source_id: str) -> RawDocument:
        _, path = source_id.split(":", 1)
        ext = PurePosixPath(path).suffix.lower()

        content = await self.run_cli_raw([
            "api", f"/repos/{self.repo}/contents/{path}?ref={self.branch}",
            "-H", "Accept: application/vnd.github.raw+json",
        ])

        content_type = "text/markdown" if ext == ".md" else "text/plain"

        return RawDocument(
            content=content,
            content_type=content_type,
            source_id=source_id,
            title=PurePosixPath(path).name,
            source_url=f"https://github.com/{self.repo}/blob/{self.branch}/{path}",
        )

    async def get_content_hash(self, source_id: str) -> str:
        return self._tree_cache[source_id]
```

- [ ] **Step 6: Run all GitHub connector tests to verify they pass**

Run: `python -m pytest tests/test_ingestion/test_github_connector.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/pam/ingestion/connectors/github.py tests/test_ingestion/test_github_connector.py
git commit -m "feat: add GitHubConnector fetch_document and get_content_hash"
```

---

### Task 5: GwsDocsConnector

**Files:**
- Create: `src/pam/ingestion/connectors/gws_docs.py`
- Create: `tests/test_ingestion/test_gws_docs_connector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ingestion/test_gws_docs_connector.py
"""Tests for GWS Docs CLI connector."""

import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.gws_docs import GwsDocsConnector


DRIVE_LIST_RESPONSE = {
    "files": [
        {"id": "doc1", "name": "Design Doc", "webViewLink": "https://docs.google.com/doc1", "modifiedTime": "2024-06-01T12:00:00Z"},
        {"id": "doc2", "name": "Meeting Notes", "webViewLink": "https://docs.google.com/doc2", "modifiedTime": "2024-07-01T10:00:00Z"},
    ],
}


@pytest.fixture
def connector():
    return GwsDocsConnector(folder_ids=["folder_abc"])


class TestListDocuments:
    async def test_returns_documents_from_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=DRIVE_LIST_RESPONSE):
            docs = await connector.list_documents()

        assert len(docs) == 2
        assert all(isinstance(d, DocumentInfo) for d in docs)
        assert docs[0].source_id == "doc1"
        assert docs[0].title == "Design Doc"
        assert docs[0].source_url == "https://docs.google.com/doc1"

    async def test_handles_empty_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={"files": []}):
            docs = await connector.list_documents()
        assert docs == []

    async def test_multiple_folders(self):
        connector = GwsDocsConnector(folder_ids=["f1", "f2"])
        responses = [
            {"files": [{"id": "d1", "name": "D1", "webViewLink": "url1", "modifiedTime": "2024-01-01T00:00:00Z"}]},
            {"files": [{"id": "d2", "name": "D2", "webViewLink": "url2", "modifiedTime": "2024-01-01T00:00:00Z"}]},
        ]
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          side_effect=responses):
            docs = await connector.list_documents()
        assert len(docs) == 2


class TestFetchDocument:
    async def test_exports_as_docx(self, connector):
        docx_bytes = b"fake docx content"
        with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                          return_value=docx_bytes):
            doc = await connector.fetch_document("doc1")

        assert isinstance(doc, RawDocument)
        assert doc.content == docx_bytes
        assert doc.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert doc.source_id == "doc1"

    async def test_calls_export_api(self, connector):
        mock_raw = AsyncMock(return_value=b"bytes")
        with patch.object(connector, "run_cli_raw", mock_raw):
            await connector.fetch_document("doc123")
        args = mock_raw.call_args[0][0]
        assert "export" in " ".join(args)
        assert "doc123" in " ".join(args)


class TestGetContentHash:
    async def test_returns_md5_from_api(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={"md5Checksum": "abc123hash"}):
            result = await connector.get_content_hash("doc1")
        assert result == "abc123hash"

    async def test_falls_back_to_sha256(self, connector):
        content = b"exported docx"
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={}):
            with patch.object(connector, "run_cli_raw", new_callable=AsyncMock,
                              return_value=content):
                result = await connector.get_content_hash("doc1")
        assert result == hashlib.sha256(content).hexdigest()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_gws_docs_connector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GwsDocsConnector**

```python
# src/pam/ingestion/connectors/gws_docs.py
"""Google Docs connector via gws CLI."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector

logger = structlog.get_logger()

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GwsDocsConnector(CliConnector):
    """Ingest Google Docs via gws CLI, exporting as DOCX."""

    cli_binary = "gws"

    def __init__(self, folder_ids: list[str] | None = None) -> None:
        self.folder_ids = folder_ids or []

    async def list_documents(self) -> list[DocumentInfo]:
        docs: list[DocumentInfo] = []

        for folder_id in self.folder_ids:
            query = f'mimeType="{GOOGLE_DOC_MIME}" and "{folder_id}" in parents'
            params = json.dumps({"q": query, "pageSize": 100})
            result = await self.run_cli([
                "drive", "files", "list",
                "--params", params,
                "--page-all",
            ])
            for f in result.get("files", []):
                modified_at = (
                    datetime.fromisoformat(f["modifiedTime"])
                    if f.get("modifiedTime") else None
                )
                docs.append(DocumentInfo(
                    source_id=f["id"],
                    title=f["name"],
                    source_url=f.get("webViewLink"),
                    modified_at=modified_at,
                ))

        logger.info("gws_docs_list_documents", folder_count=len(self.folder_ids), count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        params = json.dumps({
            "fileId": source_id,
            "mimeType": DOCX_MIME,
        })
        content = await self.run_cli_raw([
            "drive", "files", "export",
            "--params", params,
        ])
        return RawDocument(
            content=content,
            content_type=DOCX_MIME,
            source_id=source_id,
            title=source_id,  # Title set during pipeline from list_documents
        )

    async def get_content_hash(self, source_id: str) -> str:
        params = json.dumps({"fileId": source_id, "fields": "md5Checksum"})
        result = await self.run_cli([
            "drive", "files", "get",
            "--params", params,
        ])
        md5: str | None = result.get("md5Checksum")
        if md5:
            return md5
        # Fallback: export and hash (Google Docs lack md5Checksum)
        content = await self.run_cli_raw([
            "drive", "files", "export",
            "--params", json.dumps({"fileId": source_id, "mimeType": DOCX_MIME}),
        ])
        return hashlib.sha256(content).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_gws_docs_connector.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/ingestion/connectors/gws_docs.py tests/test_ingestion/test_gws_docs_connector.py
git commit -m "feat: add GwsDocsConnector via gws CLI"
```

---

### Task 6: GwsSheetsConnector

**Files:**
- Create: `src/pam/ingestion/connectors/gws_sheets.py`
- Create: `tests/test_ingestion/test_gws_sheets_connector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ingestion/test_gws_sheets_connector.py
"""Tests for GWS Sheets CLI connector."""

import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector


DRIVE_LIST_RESPONSE = {
    "files": [
        {"id": "sheet1", "name": "Budget", "webViewLink": "https://sheets.google.com/sheet1", "modifiedTime": "2024-06-01T00:00:00Z"},
    ],
}

SPREADSHEET_RESPONSE = {
    "properties": {"title": "Budget"},
    "sheets": [
        {
            "properties": {"title": "Q1"},
            "data": [{"rowData": [
                {"values": [{"formattedValue": "Category"}, {"formattedValue": "Amount"}]},
                {"values": [{"formattedValue": "Rent"}, {"formattedValue": "2000"}]},
            ]}],
        }
    ],
}


@pytest.fixture
def connector():
    return GwsSheetsConnector(folder_ids=["folder_abc"])


class TestListDocuments:
    async def test_returns_sheets_from_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=DRIVE_LIST_RESPONSE):
            docs = await connector.list_documents()
        assert len(docs) == 1
        assert docs[0].source_id == "sheet1"
        assert docs[0].title == "Budget"

    async def test_handles_empty_folder(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value={"files": []}):
            docs = await connector.list_documents()
        assert docs == []


class TestFetchDocument:
    async def test_returns_json_with_sheet_data(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=SPREADSHEET_RESPONSE):
            doc = await connector.fetch_document("sheet1")

        assert isinstance(doc, RawDocument)
        assert doc.content_type == "application/vnd.google-sheets+json"
        assert doc.source_id == "sheet1"
        parsed = json.loads(doc.content)
        assert "title" in parsed
        assert "tabs" in parsed

    async def test_calls_sheets_api(self, connector):
        mock_run = AsyncMock(return_value=SPREADSHEET_RESPONSE)
        with patch.object(connector, "run_cli", mock_run):
            await connector.fetch_document("sheet123")
        args = mock_run.call_args[0][0]
        assert "spreadsheets" in " ".join(args)
        assert "sheet123" in " ".join(args)


class TestGetContentHash:
    async def test_hashes_fetched_content(self, connector):
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=SPREADSHEET_RESPONSE):
            result = await connector.get_content_hash("sheet1")

        # Re-fetch to compute expected hash
        with patch.object(connector, "run_cli", new_callable=AsyncMock,
                          return_value=SPREADSHEET_RESPONSE):
            doc = await connector.fetch_document("sheet1")
        expected = hashlib.sha256(doc.content).hexdigest()
        assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_gws_sheets_connector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GwsSheetsConnector**

```python
# src/pam/ingestion/connectors/gws_sheets.py
"""Google Sheets connector via gws CLI."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import structlog

from pam.common.models import DocumentInfo, RawDocument
from pam.ingestion.connectors.cli_base import CliConnector
from pam.ingestion.connectors.google_sheets import detect_regions

logger = structlog.get_logger()

SHEETS_MIME = "application/vnd.google-apps.spreadsheet"


class GwsSheetsConnector(CliConnector):
    """Ingest Google Sheets via gws CLI."""

    cli_binary = "gws"

    def __init__(self, folder_ids: list[str] | None = None) -> None:
        self.folder_ids = folder_ids or []

    async def list_documents(self) -> list[DocumentInfo]:
        docs: list[DocumentInfo] = []

        for folder_id in self.folder_ids:
            query = f'mimeType="{SHEETS_MIME}" and "{folder_id}" in parents'
            params = json.dumps({"q": query, "pageSize": 100})
            result = await self.run_cli([
                "drive", "files", "list",
                "--params", params,
                "--page-all",
            ])
            for f in result.get("files", []):
                modified_at = (
                    datetime.fromisoformat(f["modifiedTime"])
                    if f.get("modifiedTime") else None
                )
                docs.append(DocumentInfo(
                    source_id=f["id"],
                    title=f["name"],
                    source_url=f.get("webViewLink"),
                    modified_at=modified_at,
                ))

        logger.info("gws_sheets_list_documents", folder_count=len(self.folder_ids), count=len(docs))
        return docs

    async def fetch_document(self, source_id: str) -> RawDocument:
        params = json.dumps({"spreadsheetId": source_id, "includeGridData": True})
        data = await self.run_cli([
            "sheets", "spreadsheets", "get",
            "--params", params,
        ])

        title = data.get("properties", {}).get("title", source_id)
        tabs: dict[str, dict] = {}

        for sheet in data.get("sheets", []):
            tab_name = sheet.get("properties", {}).get("title", "Sheet")
            rows: list[list[str]] = []
            for grid in sheet.get("data", []):
                for row_data in grid.get("rowData", []):
                    cells = [
                        cell.get("formattedValue", "")
                        for cell in row_data.get("values", [])
                    ]
                    rows.append(cells)

            regions = detect_regions(rows) if rows else []
            tabs[tab_name] = {
                "rows": rows,
                "regions": [
                    {"type": r.type, "start_row": r.start_row, "end_row": r.end_row,
                     "start_col": r.start_col, "end_col": r.end_col, "header": r.header}
                    for r in regions
                ],
            }

        content_json = json.dumps({"title": title, "tabs": tabs}, ensure_ascii=False)

        return RawDocument(
            content=content_json.encode(),
            content_type="application/vnd.google-sheets+json",
            source_id=source_id,
            title=title,
            metadata={"tab_count": len(tabs)},
        )

    async def get_content_hash(self, source_id: str) -> str:
        doc = await self.fetch_document(source_id)
        return hashlib.sha256(doc.content).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_gws_sheets_connector.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/ingestion/connectors/gws_sheets.py tests/test_ingestion/test_gws_sheets_connector.py
git commit -m "feat: add GwsSheetsConnector via gws CLI"
```

---

### Task 7: Connector Factory and __init__.py Exports

**Files:**
- Create: `src/pam/ingestion/connectors/factory.py`
- Modify: `src/pam/ingestion/connectors/__init__.py`
- Create: `tests/test_ingestion/test_connector_factory.py`

- [ ] **Step 1: Write failing tests for factory**

```python
# tests/test_ingestion/test_connector_factory.py
"""Tests for connector factory functions."""

import os
from unittest.mock import patch

import pytest

from pam.common.config import Settings
from pam.ingestion.connectors.factory import (
    get_google_docs_connector,
    get_google_sheets_connector,
)
from pam.ingestion.connectors.google_docs import GoogleDocsConnector
from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector
from pam.ingestion.connectors.gws_docs import GwsDocsConnector
from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector


def _make_settings(**overrides) -> Settings:
    defaults = {
        "database_url": "postgresql+psycopg://x:x@localhost/x",
        "openai_api_key": "test",
        "anthropic_api_key": "test",
    }
    with patch.dict(os.environ, {}, clear=True):
        return Settings(**{**defaults, **overrides})


class TestGetGoogleDocsConnector:
    def test_returns_gws_when_cli_enabled(self):
        cfg = _make_settings(use_cli_connectors=True)
        conn = get_google_docs_connector(cfg)
        assert isinstance(conn, GwsDocsConnector)

    def test_returns_api_when_cli_disabled(self):
        cfg = _make_settings(use_cli_connectors=False)
        conn = get_google_docs_connector(cfg)
        assert isinstance(conn, GoogleDocsConnector)


class TestGetGoogleSheetsConnector:
    def test_returns_gws_when_cli_enabled(self):
        cfg = _make_settings(use_cli_connectors=True)
        conn = get_google_sheets_connector(cfg)
        assert isinstance(conn, GwsSheetsConnector)

    def test_returns_api_when_cli_disabled(self):
        cfg = _make_settings(use_cli_connectors=False)
        conn = get_google_sheets_connector(cfg)
        assert isinstance(conn, GoogleSheetsConnector)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_connector_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pam.ingestion.connectors.factory'`

- [ ] **Step 3: Implement factory**

```python
# src/pam/ingestion/connectors/factory.py
"""Factory functions for selecting between API and CLI connectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pam.ingestion.connectors.base import BaseConnector

if TYPE_CHECKING:
    from pam.common.config import Settings


def get_google_docs_connector(config: Settings) -> BaseConnector:
    """Return GwsDocsConnector when CLI connectors enabled, else GoogleDocsConnector."""
    if config.use_cli_connectors:
        from pam.ingestion.connectors.gws_docs import GwsDocsConnector

        return GwsDocsConnector(folder_ids=getattr(config, "google_folder_ids", []))

    from pam.ingestion.connectors.google_docs import GoogleDocsConnector

    return GoogleDocsConnector(
        credentials_path=getattr(config, "google_credentials_path", None),
        folder_ids=getattr(config, "google_folder_ids", []),
    )


def get_google_sheets_connector(config: Settings) -> BaseConnector:
    """Return GwsSheetsConnector when CLI connectors enabled, else GoogleSheetsConnector."""
    if config.use_cli_connectors:
        from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector

        return GwsSheetsConnector(folder_ids=getattr(config, "google_folder_ids", []))

    from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector

    return GoogleSheetsConnector(
        credentials_path=getattr(config, "google_credentials_path", None),
        folder_ids=getattr(config, "google_folder_ids", []),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_connector_factory.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Update connectors/__init__.py**

```python
# src/pam/ingestion/connectors/__init__.py
"""Document connectors — abstract base and implementations."""

from pam.ingestion.connectors.base import BaseConnector
from pam.ingestion.connectors.cli_base import CliConnector, ConnectorError
from pam.ingestion.connectors.factory import (
    get_google_docs_connector,
    get_google_sheets_connector,
)
from pam.ingestion.connectors.github import GitHubConnector
from pam.ingestion.connectors.google_docs import GoogleDocsConnector
from pam.ingestion.connectors.google_sheets import GoogleSheetsConnector
from pam.ingestion.connectors.gws_docs import GwsDocsConnector
from pam.ingestion.connectors.gws_sheets import GwsSheetsConnector
from pam.ingestion.connectors.markdown import MarkdownConnector

__all__ = [
    "BaseConnector",
    "CliConnector",
    "ConnectorError",
    "GitHubConnector",
    "GoogleDocsConnector",
    "GoogleSheetsConnector",
    "GwsDocsConnector",
    "GwsSheetsConnector",
    "MarkdownConnector",
    "get_google_docs_connector",
    "get_google_sheets_connector",
]
```

- [ ] **Step 6: Verify imports work**

Run: `python -c "from pam.ingestion.connectors import GitHubConnector, CliConnector, ConnectorError, get_google_docs_connector; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/pam/ingestion/connectors/factory.py src/pam/ingestion/connectors/__init__.py tests/test_ingestion/test_connector_factory.py
git commit -m "feat: add connector factory and __init__ exports"
```

---

### Task 8: Task Manager — GitHub and Sync Background Tasks

**Files:**
- Modify: `src/pam/ingestion/task_manager.py`
- Create: `tests/test_ingestion/test_task_manager_cli.py`

- [ ] **Step 1: Write failing tests for background task functions**

```python
# tests/test_ingestion/test_task_manager_cli.py
"""Tests for CLI connector task manager functions."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.ingestion.task_manager import (
    run_github_ingestion_background,
    run_sync_background,
)


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock(return_value=session)
    return factory


@pytest.fixture
def mock_es_client():
    return AsyncMock()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.dimensions = 1536
    return embedder


class TestRunGithubIngestionBackground:
    async def test_creates_github_connector_and_runs_pipeline(
        self, mock_session_factory, mock_es_client, mock_embedder
    ):
        task_id = uuid.uuid4()
        repo_config = {"repo": "owner/repo", "branch": "main", "paths": ["docs/"], "extensions": [".md"]}

        with patch("pam.ingestion.task_manager.GitHubConnector") as MockGH, \
             patch("pam.ingestion.task_manager.DoclingParser"), \
             patch("pam.ingestion.task_manager.ElasticsearchStore"), \
             patch("pam.ingestion.task_manager.IngestionPipeline") as MockPipeline:
            mock_pipeline = AsyncMock()
            mock_pipeline.ingest_all = AsyncMock(return_value=[])
            mock_pipeline.connector = AsyncMock()
            mock_pipeline.connector.list_documents = AsyncMock(return_value=[])
            MockPipeline.return_value = mock_pipeline

            mock_gh_instance = AsyncMock()
            mock_gh_instance.list_documents = AsyncMock(return_value=[])
            MockGH.return_value = mock_gh_instance

            await run_github_ingestion_background(
                task_id=task_id,
                repo_config=repo_config,
                es_client=mock_es_client,
                embedder=mock_embedder,
                session_factory=mock_session_factory,
            )

        MockGH.assert_called_once_with(
            repo="owner/repo", branch="main", paths=["docs/"], extensions=[".md"],
        )


class TestRunSyncBackground:
    async def test_iterates_github_sources(
        self, mock_session_factory, mock_es_client, mock_embedder
    ):
        task_id = uuid.uuid4()
        github_repos = [{"repo": "org/wiki", "branch": "main", "paths": [], "extensions": [".md"]}]

        with patch("pam.ingestion.task_manager.GitHubConnector") as MockGH, \
             patch("pam.ingestion.task_manager.DoclingParser"), \
             patch("pam.ingestion.task_manager.ElasticsearchStore"), \
             patch("pam.ingestion.task_manager.IngestionPipeline") as MockPipeline:
            mock_pipeline = AsyncMock()
            mock_pipeline.ingest_all = AsyncMock(return_value=[])
            mock_pipeline.connector = AsyncMock()
            mock_pipeline.connector.list_documents = AsyncMock(return_value=[])
            MockPipeline.return_value = mock_pipeline

            mock_gh_instance = AsyncMock()
            mock_gh_instance.list_documents = AsyncMock(return_value=[])
            MockGH.return_value = mock_gh_instance

            await run_sync_background(
                task_id=task_id,
                sources=["github"],
                github_repos=github_repos,
                es_client=mock_es_client,
                embedder=mock_embedder,
                session_factory=mock_session_factory,
            )

        MockGH.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_task_manager_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_github_ingestion_background'`

- [ ] **Step 3: Add GitHub and sync background functions to task_manager.py**

Add this import after the existing `MarkdownConnector` import (line 24 of `src/pam/ingestion/task_manager.py`):

```python
from pam.ingestion.connectors.github import GitHubConnector
```

Add these functions before `recover_stale_tasks` (before line 240 of `src/pam/ingestion/task_manager.py`):

```python
def spawn_github_ingestion_task(
    task_id: uuid.UUID,
    repo_config: dict,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Spawn a background asyncio task for GitHub ingestion."""
    asyncio_task = asyncio.create_task(
        run_github_ingestion_background(
            task_id, repo_config, es_client, embedder, session_factory,
            cache_service, graph_service, skip_graph, vdb_store,
        ),
        name=f"ingest-github-{task_id}",
    )
    _running_tasks[task_id] = asyncio_task
    logger.info("github_task_spawned", task_id=str(task_id), repo=repo_config.get("repo"))


async def run_github_ingestion_background(
    task_id: uuid.UUID,
    repo_config: dict,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Background coroutine for GitHub repo ingestion."""
    try:
        async with session_factory() as status_session:
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await status_session.commit()

            connector = GitHubConnector(
                repo=repo_config["repo"],
                branch=repo_config.get("branch", "main"),
                paths=repo_config.get("paths", []),
                extensions=repo_config.get("extensions", [".md", ".txt"]),
            )
            docs = await connector.list_documents()
            total = len(docs)

            await status_session.execute(
                update(IngestionTask).where(IngestionTask.id == task_id).values(total_documents=total)
            )
            await status_session.commit()

            if total == 0:
                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="completed", completed_at=datetime.now(UTC))
                )
                await status_session.commit()
                return

            async def on_progress(result: IngestionResult) -> None:
                result_entry = [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                        "graph_synced": result.graph_synced,
                        "graph_entities_extracted": result.graph_entities_extracted,
                    }
                ]
                succeeded_inc = 1 if not result.error and not result.skipped else 0
                skipped_inc = 1 if result.skipped else 0
                failed_inc = 1 if result.error else 0

                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=IngestionTask.processed_documents + 1,
                        succeeded=IngestionTask.succeeded + succeeded_inc,
                        skipped=IngestionTask.skipped + skipped_inc,
                        failed=IngestionTask.failed + failed_inc,
                        results=IngestionTask.results
                        + cast(literal(json_module.dumps(result_entry)), JSONB),
                    )
                )
                await status_session.commit()

            async with session_factory() as pipeline_session:
                parser = DoclingParser()
                es_store = ElasticsearchStore(
                    es_client,
                    index_name=settings.elasticsearch_index,
                    embedding_dims=settings.embedding_dims,
                )
                pipeline = IngestionPipeline(
                    connector=connector,
                    parser=parser,
                    embedder=embedder,
                    es_store=es_store,
                    session=pipeline_session,
                    source_type="github",
                    progress_callback=on_progress,
                    graph_service=graph_service,
                    vdb_store=vdb_store,
                    skip_graph=skip_graph,
                )
                await pipeline.ingest_all()

            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await status_session.commit()

            if cache_service:
                try:
                    cleared = await cache_service.invalidate_search()
                    logger.info("cache_invalidated_after_github_ingest", keys_cleared=cleared)
                except Exception:
                    logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("github_task_completed", task_id=str(task_id))

    except Exception as e:
        logger.exception("github_task_failed", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="failed", error=str(e), completed_at=datetime.now(UTC))
                )
                await err_session.commit()
        except Exception:
            logger.exception("github_task_failed_status_update_error", task_id=str(task_id))
    finally:
        _running_tasks.pop(task_id, None)


def spawn_sync_task(
    task_id: uuid.UUID,
    sources: list[str],
    github_repos: list[dict],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Spawn a background asyncio task for multi-source sync."""
    asyncio_task = asyncio.create_task(
        run_sync_background(
            task_id, sources, github_repos, es_client, embedder, session_factory,
            cache_service, graph_service, skip_graph, vdb_store,
        ),
        name=f"ingest-sync-{task_id}",
    )
    _running_tasks[task_id] = asyncio_task
    logger.info("sync_task_spawned", task_id=str(task_id), sources=sources)


async def run_sync_background(
    task_id: uuid.UUID,
    sources: list[str],
    github_repos: list[dict],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Background coroutine for multi-source sync."""
    try:
        async with session_factory() as status_session:
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await status_session.commit()

            all_results: list[IngestionResult] = []
            total_docs = 0

            async def on_progress(result: IngestionResult) -> None:
                result_entry = [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                    }
                ]
                succeeded_inc = 1 if not result.error and not result.skipped else 0
                skipped_inc = 1 if result.skipped else 0
                failed_inc = 1 if result.error else 0

                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=IngestionTask.processed_documents + 1,
                        succeeded=IngestionTask.succeeded + succeeded_inc,
                        skipped=IngestionTask.skipped + skipped_inc,
                        failed=IngestionTask.failed + failed_inc,
                        results=IngestionTask.results
                        + cast(literal(json_module.dumps(result_entry)), JSONB),
                    )
                )
                await status_session.commit()

            # GitHub sources
            if "github" in sources:
                for repo_config in github_repos:
                    connector = GitHubConnector(
                        repo=repo_config["repo"],
                        branch=repo_config.get("branch", "main"),
                        paths=repo_config.get("paths", []),
                        extensions=repo_config.get("extensions", [".md", ".txt"]),
                    )
                    docs = await connector.list_documents()
                    total_docs += len(docs)

                    await status_session.execute(
                        update(IngestionTask)
                        .where(IngestionTask.id == task_id)
                        .values(total_documents=total_docs)
                    )
                    await status_session.commit()

                    async with session_factory() as pipeline_session:
                        parser = DoclingParser()
                        es_store = ElasticsearchStore(
                            es_client,
                            index_name=settings.elasticsearch_index,
                            embedding_dims=settings.embedding_dims,
                        )
                        pipeline = IngestionPipeline(
                            connector=connector,
                            parser=parser,
                            embedder=embedder,
                            es_store=es_store,
                            session=pipeline_session,
                            source_type="github",
                            progress_callback=on_progress,
                            graph_service=graph_service,
                            vdb_store=vdb_store,
                            skip_graph=skip_graph,
                        )
                        results = await pipeline.ingest_all()
                        all_results.extend(results)

            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await status_session.commit()

            if cache_service:
                try:
                    cleared = await cache_service.invalidate_search()
                    logger.info("cache_invalidated_after_sync", keys_cleared=cleared)
                except Exception:
                    logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("sync_task_completed", task_id=str(task_id), total_results=len(all_results))

    except Exception as e:
        logger.exception("sync_task_failed", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="failed", error=str(e), completed_at=datetime.now(UTC))
                )
                await err_session.commit()
        except Exception:
            logger.exception("sync_task_failed_status_update_error", task_id=str(task_id))
    finally:
        _running_tasks.pop(task_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_task_manager_cli.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/ingestion/task_manager.py tests/test_ingestion/test_task_manager_cli.py
git commit -m "feat: add GitHub and sync background task functions"
```

---

### Task 9: API Endpoints — POST /ingest/github and POST /ingest/sync

**Files:**
- Modify: `src/pam/api/routes/ingest.py`
- Create: `tests/test_ingestion/test_ingest_api_github.py`

- [ ] **Step 1: Write failing tests for the new endpoints**

```python
# tests/test_ingestion/test_ingest_api_github.py
"""Tests for GitHub and sync ingest API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pam.api.routes.ingest import router
from pam.common.models import IngestionTask


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = MagicMock()
    app.state.cache_service = None
    app.state.graph_service = None
    app.state.vdb_store = None
    return app


@pytest.fixture
def mock_task():
    task = MagicMock(spec=IngestionTask)
    task.id = uuid.uuid4()
    return task


class TestIngestGithub:
    async def test_returns_202_with_task_id(self, app, mock_task):
        with patch("pam.api.routes.ingest.create_task", new_callable=AsyncMock, return_value=mock_task), \
             patch("pam.api.routes.ingest.spawn_github_ingestion_task") as mock_spawn, \
             patch("pam.api.routes.ingest.require_admin", return_value=None), \
             patch("pam.api.routes.ingest.get_db", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_es_client", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_embedder", return_value=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/github", json={
                    "repo": "owner/repo",
                    "branch": "main",
                    "paths": ["docs/"],
                })
            assert resp.status_code == 202
            data = resp.json()
            assert "task_id" in data

    async def test_requires_repo_field(self, app):
        with patch("pam.api.routes.ingest.require_admin", return_value=None), \
             patch("pam.api.routes.ingest.get_db", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_es_client", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_embedder", return_value=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/github", json={})
            assert resp.status_code == 422


class TestIngestSync:
    async def test_returns_202_with_task_id(self, app, mock_task):
        with patch("pam.api.routes.ingest.create_task", new_callable=AsyncMock, return_value=mock_task), \
             patch("pam.api.routes.ingest.spawn_sync_task") as mock_spawn, \
             patch("pam.api.routes.ingest.require_admin", return_value=None), \
             patch("pam.api.routes.ingest.get_db", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_es_client", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_embedder", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.settings") as mock_settings:
            mock_settings.github_repos = [{"repo": "org/wiki"}]
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/sync", json={
                    "sources": ["github"],
                })
            assert resp.status_code == 202

    async def test_defaults_sources_to_all(self, app, mock_task):
        with patch("pam.api.routes.ingest.create_task", new_callable=AsyncMock, return_value=mock_task), \
             patch("pam.api.routes.ingest.spawn_sync_task") as mock_spawn, \
             patch("pam.api.routes.ingest.require_admin", return_value=None), \
             patch("pam.api.routes.ingest.get_db", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_es_client", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.get_embedder", return_value=AsyncMock()), \
             patch("pam.api.routes.ingest.settings") as mock_settings:
            mock_settings.github_repos = []
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/sync", json={})
            assert resp.status_code == 202
            # spawn_sync_task should receive default sources list
            call_kwargs = mock_spawn.call_args
            sources_arg = call_kwargs.kwargs.get("sources") or call_kwargs[0][1]
            assert "github" in sources_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingestion/test_ingest_api_github.py -v`
Expected: FAIL — endpoint not found (404)

- [ ] **Step 3: Update imports and add request models + endpoints**

In `src/pam/api/routes/ingest.py`, replace the task_manager import line:

```python
# Replace:
from pam.ingestion.task_manager import create_task, get_task, spawn_ingestion_task

# With:
from pam.ingestion.task_manager import (
    create_task,
    get_task,
    spawn_github_ingestion_task,
    spawn_ingestion_task,
    spawn_sync_task,
)
```

Add new request models after `IngestFolderRequest` (after line 39):

```python
class IngestGithubRequest(BaseModel):
    repo: str
    branch: str = "main"
    paths: list[str] = []
    extensions: list[str] = [".md", ".txt"]


class IngestSyncRequest(BaseModel):
    sources: list[str] = ["github", "google_docs", "google_sheets"]
    skip_graph: bool = False
```

Add new endpoints before the `sync-graph` endpoint (before line 164):

```python
@router.post("/ingest/github", response_model=TaskCreatedResponse, status_code=202)
async def ingest_github(
    request: Request,
    body: IngestGithubRequest,
    skip_graph: bool = Query(default=False, description="Skip graph extraction"),
    db: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch = Depends(get_es_client),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    _admin: User | None = Depends(require_admin),
):
    """Start background ingestion of files from a GitHub repo via gh CLI."""
    repo_config = {
        "repo": body.repo,
        "branch": body.branch,
        "paths": body.paths,
        "extensions": body.extensions,
    }
    task = await create_task(body.repo, db)
    graph_service = getattr(request.app.state, "graph_service", None)
    vdb_store = getattr(request.app.state, "vdb_store", None)
    spawn_github_ingestion_task(
        task.id,
        repo_config,
        es_client,
        embedder,
        session_factory=request.app.state.session_factory,
        cache_service=request.app.state.cache_service,
        graph_service=graph_service,
        skip_graph=skip_graph,
        vdb_store=vdb_store,
    )
    return TaskCreatedResponse(task_id=task.id)


@router.post("/ingest/sync", response_model=TaskCreatedResponse, status_code=202)
async def ingest_sync(
    request: Request,
    body: IngestSyncRequest,
    db: AsyncSession = Depends(get_db),
    es_client: AsyncElasticsearch = Depends(get_es_client),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    _admin: User | None = Depends(require_admin),
):
    """Sync all configured sources (GitHub repos, Google folders)."""
    task = await create_task("sync", db)
    graph_service = getattr(request.app.state, "graph_service", None)
    vdb_store = getattr(request.app.state, "vdb_store", None)
    spawn_sync_task(
        task.id,
        sources=body.sources,
        github_repos=settings.github_repos,
        es_client=es_client,
        embedder=embedder,
        session_factory=request.app.state.session_factory,
        cache_service=request.app.state.cache_service,
        graph_service=graph_service,
        skip_graph=body.skip_graph,
        vdb_store=vdb_store,
    )
    return TaskCreatedResponse(task_id=task.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingestion/test_ingest_api_github.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run existing ingest API tests to verify no regressions**

Run: `python -m pytest tests/ -k "ingest" -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/api/routes/ingest.py tests/test_ingestion/test_ingest_api_github.py
git commit -m "feat: add POST /ingest/github and POST /ingest/sync endpoints"
```

---

### Task 10: Integration Test (Requires gh auth)

**Files:**
- Create: `tests/integration/test_github_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_github_integration.py
"""Integration test for GitHubConnector against a real public repo.

Requires: gh CLI installed and authenticated (gh auth login).
Run with: pytest tests/integration/ -m integration -v
"""

import pytest

from pam.ingestion.connectors.github import GitHubConnector


@pytest.mark.integration
class TestGitHubIntegration:
    """Tests against a small, stable public repo (github/gitignore)."""

    async def test_list_documents_returns_files(self):
        connector = GitHubConnector(
            repo="github/gitignore",
            branch="main",
            extensions=[".gitignore"],
        )
        available = await connector.check_available()
        if not available:
            pytest.skip("gh CLI not available")

        docs = await connector.list_documents()
        assert len(docs) > 0
        assert all(d.source_id.startswith("github/gitignore:") for d in docs)

    async def test_fetch_document_returns_content(self):
        connector = GitHubConnector(
            repo="github/gitignore",
            branch="main",
            paths=[""],
            extensions=[".gitignore"],
        )
        available = await connector.check_available()
        if not available:
            pytest.skip("gh CLI not available")

        docs = await connector.list_documents()
        assert len(docs) > 0

        # Fetch the first file
        doc = await connector.fetch_document(docs[0].source_id)
        assert len(doc.content) > 0
        assert doc.content_type == "text/plain"

    async def test_content_hash_uses_cached_sha(self):
        connector = GitHubConnector(
            repo="github/gitignore",
            branch="main",
            extensions=[".gitignore"],
        )
        available = await connector.check_available()
        if not available:
            pytest.skip("gh CLI not available")

        docs = await connector.list_documents()
        assert len(docs) > 0

        sha = await connector.get_content_hash(docs[0].source_id)
        assert len(sha) == 40  # Git SHA-1 is 40 hex chars
```

- [ ] **Step 2: Verify test is skipped in normal runs**

Run: `python -m pytest tests/integration/test_github_integration.py -v`
Expected: All tests SKIPPED (not marked for default collection) or PASSED if `gh` is available

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_github_integration.py
git commit -m "test: add GitHub connector integration tests"
```

---

### Task 11: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS, no regressions

- [ ] **Step 2: Run linter**

Run: `python -m ruff check src/pam/ingestion/connectors/ src/pam/api/routes/ingest.py src/pam/common/config.py`
Expected: No errors

- [ ] **Step 3: Verify all new imports work**

Run: `python -c "from pam.ingestion.connectors import GitHubConnector, GwsDocsConnector, GwsSheetsConnector, ConnectorError, get_google_docs_connector; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 4: Commit any lint fixes if needed**

```bash
git add -u
git commit -m "fix: lint and type fixes for CLI connectors"
```
