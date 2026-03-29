# CLI-First Connectors: GitHub + Google Workspace

**Date:** 2026-03-29
**Status:** Approved

## Motivation

Adopt a CLI-first connector architecture for document ingestion:

- **Simpler auth** — leverage `gh auth login` and `gws auth login` instead of managing tokens/credentials in the app
- **Consistency** — all connectors follow the same pattern: subprocess → JSON → `BaseConnector` interface
- **LLM-friendly** — CLIs with structured JSON output are the easiest interface for machines (including LLM agents) to use

## Scope

1. **New `CliConnector` base class** — shared subprocess + JSON plumbing
2. **New `GitHubConnector`** — ingest `.md`/`.txt` files from GitHub repos via `gh` CLI
3. **New `GwsDocsConnector` and `GwsSheetsConnector`** — `gws` CLI alternatives to existing Google API connectors
4. **Config-driven toggle** — `USE_CLI_CONNECTORS=true` switches Google connectors to `gws`; GitHub always uses `gh`
5. **New API endpoints** — `POST /ingest/github` (ad-hoc) and `POST /ingest/sync` (all configured sources)

## Architecture

### Connector Hierarchy

```
BaseConnector (abstract)
├── CliConnector (abstract - subprocess + JSON helpers)
│   ├── GitHubConnector (gh CLI)
│   ├── GwsDocsConnector (gws CLI)
│   └── GwsSheetsConnector (gws CLI)
├── GoogleDocsConnector (existing, direct API)
├── GoogleSheetsConnector (existing, direct API)
└── MarkdownConnector (local filesystem)
```

Existing connectors are unchanged. The `use_cli_connectors` config flag selects between old and new Google connectors via a factory function.

### Decision: Why `gh` CLI over PyGithub/githubkit

| Factor | `gh` CLI (chosen) | PyGithub | githubkit |
|---|---|---|---|
| Async | Via `asyncio.subprocess` | No (sync only) | Native async + sync |
| Auth | `gh auth login` (zero config) | Programmatic PAT/App | Programmatic PAT/App |
| Consistency with `gws` | Same CliConnector pattern | Different pattern | Different pattern |
| LLM-friendly | Yes (text commands) | No (Python API) | No (Python API) |
| Dependencies | External binary only | requests, pynacl, pyjwt | httpx, anyio, pydantic |

PyGithub has better rate limit handling and typed responses, but architectural consistency and zero-auth setup outweigh these for our use case. Rate limit retry is handled in `CliConnector` base.

## Section 1: CliConnector Base Class

**File:** `src/pam/ingestion/connectors/cli_base.py`

```python
class CliConnector(BaseConnector, ABC):
    """Base for connectors that shell out to CLI tools."""

    cli_binary: str  # "gh" or "gws"

    async def check_available(self) -> bool:
        """Verify CLI is installed and authenticated."""

    async def run_cli(
        self, args: list[str], *, timeout: int = 30
    ) -> dict | list:
        """Run CLI command, parse JSON stdout, raise on failure."""

    async def run_cli_raw(
        self, args: list[str], *, timeout: int = 30
    ) -> bytes:
        """Run CLI command, return raw stdout (for file content)."""
```

Key behaviors:

- Uses `asyncio.create_subprocess_exec` (non-blocking)
- `run_cli` parses JSON stdout, raises `ConnectorError` on non-zero exit
- `run_cli_raw` returns raw bytes (for fetching file content without base64 decoding)
- Logs every command via structlog (command, duration, exit code)
- Configurable timeout per call (default 30s)

## Section 2: Configuration

**New settings in `config.py`:**

```python
# GitHub connector
github_repos: list[dict] = []

# CLI backend toggle
use_cli_connectors: bool = False

# CLI timeouts
cli_timeout: int = 30  # seconds per CLI call
```

**GitHub repo config structure:**

| Field | Required | Default | Description |
|---|---|---|---|
| `repo` | Yes | — | `owner/repo` format |
| `branch` | No | `"main"` | Branch/tag to ingest from |
| `paths` | No | `[]` (entire repo) | Directory prefixes to filter |
| `extensions` | No | `[".md", ".txt"]` | File extensions to include |

**Environment variable example:**

```bash
GITHUB_REPOS='[{"repo":"anthropics/claude-code","branch":"main","paths":["docs/"]},{"repo":"org/wiki","paths":["guides/"]}]'
USE_CLI_CONNECTORS=true
```

The `use_cli_connectors` flag controls Google connectors only. GitHub always uses `gh` since there's no existing alternative.

## Section 3: GitHubConnector

**File:** `src/pam/ingestion/connectors/github.py`

```python
class GitHubConnector(CliConnector):
    cli_binary = "gh"

    def __init__(self, repo: str, branch: str = "main",
                 paths: list[str] = [], extensions: list[str] = [".md", ".txt"]):
```

### list_documents() — 1 CLI call per repo

```bash
gh api /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
```

- Filters tree entries client-side by `paths` and `extensions`
- Returns `DocumentInfo` with `source_id = "{repo}:{path}"`, SHA in metadata

### get_content_hash(source_id) — free, no CLI call

- SHA already captured during `list_documents()` from the tree response
- Stored in an internal `_tree_cache: dict[source_id, sha]`
- Compared against DB's stored hash to skip unchanged files

### fetch_document(source_id) — 1 CLI call per file

```bash
gh api /repos/{owner}/{repo}/contents/{path}?ref={branch} -H "Accept: application/vnd.github.raw+json"
```

- Returns `RawDocument` with `content_type = "text/markdown"` or `"text/plain"` based on extension
- Sets `source_url` to the GitHub web URL for citation links

### Ingestion cost for 50 .md files across 2 repos

```
repo1: 1 tree call + N changed files fetched
repo2: 1 tree call + M changed files fetched
Total: 2 + (N + M) CLI calls  (skips unchanged via SHA)
```

## Section 4: GWS CLI Connectors

Two connectors replacing the existing Google ones when `USE_CLI_CONNECTORS=true`.

### GwsDocsConnector

**File:** `src/pam/ingestion/connectors/gws_docs.py`

**list_documents():**

```bash
gws drive files list --params '{"q": "mimeType=\"application/vnd.google-apps.document\" and \"FOLDER_ID\" in parents", "pageSize": 100}' --page-all
```

**fetch_document(source_id)** — export as DOCX:

```bash
gws drive files export --params '{"fileId": "ID", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}'
```

**get_content_hash(source_id):**

```bash
gws drive files get --params '{"fileId": "ID", "fields": "md5Checksum"}'
```

### GwsSheetsConnector

**File:** `src/pam/ingestion/connectors/gws_sheets.py`

**list_documents()** — same Drive listing as Docs but filtered for spreadsheet MIME type.

**fetch_document(source_id):**

```bash
gws sheets spreadsheets get --params '{"spreadsheetId": "ID", "includeGridData": true}'
```

- Passes grid data through the existing `detect_regions()` logic (reused, not rewritten)
- Returns JSON with detected regions, same as current connector

### Connector factory

```python
def get_google_docs_connector(config) -> BaseConnector:
    if config.use_cli_connectors:
        return GwsDocsConnector(folder_ids=config.google_folder_ids)
    return GoogleDocsConnector(credentials_path=config.google_credentials_path)
```

Same pattern for Sheets. Transparent to the pipeline.

## Section 5: API Endpoints

### POST /api/ingest/github — ad-hoc GitHub ingestion

```json
{
  "repo": "anthropics/claude-code",
  "branch": "main",
  "paths": ["docs/"],
  "extensions": [".md", ".txt"]
}
```

- Returns `202 Accepted` with `task_id` (same async pattern as `/ingest/folder`)
- Spawns background task via existing `TaskManager`

### POST /api/ingest/sync — sync all configured sources

```json
{
  "sources": ["github", "google_docs", "google_sheets"],
  "skip_graph": false
}
```

- `sources` is optional — defaults to all configured sources
- Iterates configured GitHub repos + Google folders
- Returns `202 Accepted` with a single `task_id` tracking all sources
- Progress callback reports per-source counts

### Existing endpoints unchanged

- `POST /api/ingest/folder` — still works for local files
- `GET /api/ingest/tasks/{task_id}` — tracks progress for all ingestion types
- `POST /api/ingest/sync-graph` — unchanged

## Section 6: Error Handling & Retry

### CLI-level errors handled in CliConnector base

| Scenario | Detection | Action |
|---|---|---|
| CLI not installed | `check_available()` on startup | Raise `ConnectorError("gh not found. Install: https://cli.github.com")` |
| Not authenticated | Exit code + stderr contains "auth" | Raise `ConnectorError("Run 'gh auth login' first")` |
| Rate limited (HTTP 429) | stderr or JSON error with "rate limit" | Retry up to 3 times with exponential backoff (5s, 15s, 45s) |
| Timeout | `asyncio.timeout` exceeded | Raise `ConnectorError` with command and timeout value |
| File too large (>100MB) | Blob API returns error | Skip file, log warning, continue with next |
| Network error | Non-zero exit, no JSON | Retry once, then raise |
| Private repo / 404 | JSON error with "Not Found" | Raise `ConnectorError` with repo name |

Pipeline-level error handling is unchanged — already handles per-document errors gracefully (logs failure, continues, reports in `IngestionResult`).

For `gws`, same retry logic applies. Auth errors suggest `gws auth login`.

## Section 7: Testing Strategy

### Unit tests

- Mock `asyncio.create_subprocess_exec` to return canned JSON responses
- Test `CliConnector.run_cli` — JSON parsing, error handling, timeout
- Test `GitHubConnector.list_documents` — tree filtering by path/extension
- Test `GitHubConnector.get_content_hash` — SHA cache behavior, skip-unchanged logic
- Test connector factory — `use_cli_connectors` toggle selects correct class

### Integration tests (require CLI auth)

- Marked with `@pytest.mark.integration`, skipped in CI by default
- `GitHubConnector` against a small public repo
- `GwsDocsConnector` against a test Google Doc
- Verify round-trip: `list_documents` → `fetch_document` → content is valid

### Existing tests unchanged

Current Google connector tests remain and cover the direct API path.

## Files to Create/Modify

| Action | File |
|---|---|
| Create | `src/pam/ingestion/connectors/cli_base.py` |
| Create | `src/pam/ingestion/connectors/github.py` |
| Create | `src/pam/ingestion/connectors/gws_docs.py` |
| Create | `src/pam/ingestion/connectors/gws_sheets.py` |
| Modify | `src/pam/common/config.py` — add GitHub + CLI settings |
| Modify | `src/pam/ingestion/connectors/__init__.py` — export new connectors |
| Modify | `src/pam/ingestion/pipeline.py` — connector factory function |
| Create | `src/pam/api/routes/ingest.py` — add `/github` and `/sync` endpoints |
| Create | `tests/unit/test_cli_connector.py` |
| Create | `tests/unit/test_github_connector.py` |
| Create | `tests/unit/test_gws_connectors.py` |
| Create | `tests/integration/test_github_integration.py` |
