# Phase 10: Bi-temporal Timestamp Pipeline Fix - Research

**Researched:** 2026-02-22
**Domain:** Ingestion pipeline data flow, bi-temporal graph modeling
**Confidence:** HIGH

## Summary

This phase closes the EXTRACT-02 gap: document modification timestamps must flow through the ingestion pipeline into Graphiti's `add_episode()` as `reference_time`, so that Neo4j edges get `valid_at` set to when the document was actually modified -- not when it was ingested.

The codebase is already partially wired for this. `DocumentInfo` has a `modified_at: datetime | None` field, and `pipeline.py` line 170 already attempts `getattr(raw_doc, "modified_at", None)`. However, `RawDocument` does NOT have a `modified_at` field, so `getattr` always returns `None`, and every `add_episode()` call falls back to `datetime.now(UTC)`. The fix is straightforward: add `modified_at` to `RawDocument`, populate it in each connector's `fetch_document()`, store it on the `Document` ORM model, and use it for both primary ingestion and the sync-graph retry endpoint.

**Primary recommendation:** Add `modified_at: datetime | None = None` to `RawDocument`, populate it from filesystem `stat().st_mtime` in the markdown connector (and from Google Drive API `modifiedTime` in the Google connectors), add a `modified_at` column to the `documents` table via Alembic migration, persist it through `upsert_document()`, and fix the sync-graph endpoint to use `doc.modified_at` instead of `doc.last_synced_at`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
None -- all implementation details are at Claude's discretion.

### Claude's Discretion
- **Timestamp source per connector**: Claude decides how each connector (filesystem, etc.) populates `modified_at` from available metadata
- **Existing data handling**: Claude decides whether already-ingested documents without `modified_at` need backfill or can remain as-is
- **Re-ingestion trigger**: Claude decides how `modified_at` changes interact with content-hash-based change detection
- **Fallback behavior**: Success criteria specify fallback to `datetime.now(UTC)` when `modified_at` is None -- Claude handles logging/warning details
- **Timezone handling**: Claude decides normalization approach for timezone-naive vs timezone-aware timestamps
- **Database migration**: Claude decides Alembic migration strategy for adding the `modified_at` column

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXTRACT-02 | Entity nodes and relationship edges created in Neo4j with bi-temporal timestamps sourced from document modified_at | All research findings directly enable this: `RawDocument.modified_at` field, connector population, `Document.modified_at` ORM column, pipeline wiring to `reference_time`, sync-graph endpoint fix |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.x (already in project) | ORM model for `Document.modified_at` column | Already used throughout `models.py` with `Mapped[]` annotations |
| Alembic | (already in project) | Migration 007 for adding column | 6 migrations already exist as pattern |
| Pydantic | v2 (already in project) | `RawDocument` schema extension | `RawDocument` is a Pydantic `BaseModel` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pathlib | stdlib | `Path.stat().st_mtime` for filesystem timestamps | Markdown connector |
| datetime | stdlib | `datetime.fromtimestamp(..., tz=UTC)` for mtime conversion | All connectors |

### Alternatives Considered
None -- this phase uses only existing project dependencies. No new libraries needed.

## Architecture Patterns

### Pattern 1: Data Flow for `modified_at`

**What:** The `modified_at` timestamp must flow through four layers: Connector -> RawDocument -> Pipeline -> PG + Graph

**Current flow (broken):**
```
MarkdownConnector.fetch_document()
  -> RawDocument (NO modified_at field)
    -> pipeline.py: getattr(raw_doc, "modified_at", None)  # always None
      -> datetime.now(UTC)  # fallback = ingestion time, NOT document time
        -> add_episode(reference_time=...)
          -> edge.valid_at = reference_time  # WRONG: set to ingestion time
```

**Fixed flow:**
```
MarkdownConnector.fetch_document()
  -> RawDocument(modified_at=stat.st_mtime as UTC datetime)
    -> pipeline.py: raw_doc.modified_at or datetime.now(UTC)
      -> extract_graph_for_document(reference_time=...)
        -> add_episode(reference_time=...)
          -> edge.valid_at = document's actual modification time
    -> pg_store.upsert_document(modified_at=raw_doc.modified_at)
      -> Document.modified_at stored for sync-graph endpoint
```

### Pattern 2: Alembic Migration Pattern (from existing project)

**What:** Simple column addition with nullable default, matching the `006_add_graph_synced.py` pattern.

**Example:**
```python
# alembic/versions/007_add_modified_at.py
def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("documents", "modified_at")
```

**Key decision:** `nullable=True` with no default. Existing documents get `NULL`, which correctly triggers the `datetime.now(UTC)` fallback on next ingestion. No backfill needed.

### Pattern 3: Connector Timestamp Population

**What:** Each connector populates `modified_at` from its source metadata.

**Markdown connector (filesystem):**
```python
async def fetch_document(self, source_id: str) -> RawDocument:
    path = Path(source_id).resolve()
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    return RawDocument(
        ...,
        modified_at=modified_at,
    )
```

**Google Docs connector (Drive API):**
```python
# Already fetches modifiedTime in list_documents but NOT in fetch_document
# Fix: add "modifiedTime" to fields in the metadata request
meta_request = service.files().get(
    fileId=source_id,
    fields="name, owners, webViewLink, modifiedTime"
)
modified_at = datetime.fromisoformat(file_meta["modifiedTime"])
```

**Google Sheets connector:**
```python
# Similar to Docs: add modifiedTime to the spreadsheet metadata request
# Note: Sheets API's spreadsheets.get doesn't return modifiedTime directly;
# need Drive API files.get for the spreadsheet ID
```

### Pattern 4: Sync-Graph Endpoint Fix

**What:** The reconciliation endpoint (`/ingest/sync-graph`) currently uses `doc.last_synced_at` as `reference_time`, which is the PG sync time -- not the document modification time.

**Current (wrong) in `ingest.py` line 195:**
```python
reference_time=doc.last_synced_at or datetime.now(UTC),
```

**Fixed:**
```python
reference_time=doc.modified_at or doc.last_synced_at or datetime.now(UTC),
```

This preserves backward compatibility: if `modified_at` is `NULL` (pre-migration documents), falls back to `last_synced_at`, then to `datetime.now(UTC)`.

### Anti-Patterns to Avoid
- **Using `os.path.getmtime()` instead of `Path.stat().st_mtime`**: The project uses `pathlib` throughout; stay consistent.
- **Storing timezone-naive datetimes**: All `DateTime` columns in the project use `timezone=True`. The `modified_at` column must also.
- **Backfilling existing data**: Unnecessary complexity. `NULL` modified_at correctly falls back to current time on next ingestion.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Filesystem mtime | Manual `os.stat` calls | `Path.stat().st_mtime` | Already used pattern in project; pathlib is standard |
| Timezone conversion | Custom TZ math | `datetime.fromtimestamp(ts, tz=UTC)` | Stdlib handles DST, leap seconds correctly |
| ISO 8601 parsing | Regex | `datetime.fromisoformat()` | Google APIs return RFC 3339 which `fromisoformat` handles since Python 3.11 |

**Key insight:** This phase is pure data plumbing. Every component (connectors, models, pipeline, endpoints) already exists. The work is adding a field and wiring it through.

## Common Pitfalls

### Pitfall 1: Timezone-Naive Timestamps from `stat().st_mtime`
**What goes wrong:** `datetime.fromtimestamp(st_mtime)` without `tz=UTC` creates a naive datetime in the system's local timezone. SQLAlchemy stores it as-is, and Graphiti interprets it differently.
**Why it happens:** `st_mtime` is a float (seconds since epoch, UTC). The default `fromtimestamp()` converts to local time without tzinfo.
**How to avoid:** Always use `datetime.fromtimestamp(st_mtime, tz=UTC)`.
**Warning signs:** Edges with `valid_at` shifted by your local UTC offset.

### Pitfall 2: Google Drive `modifiedTime` Format
**What goes wrong:** Google Drive returns timestamps as RFC 3339 strings like `"2026-01-15T10:30:00.000Z"`. Python's `fromisoformat` in 3.11+ handles the `Z` suffix, but older code may fail.
**Why it happens:** The `Z` suffix means UTC but was not supported by `fromisoformat` before Python 3.11.
**How to avoid:** Project uses Python 3.13 (per `.venv` path). `datetime.fromisoformat()` handles `Z` correctly.
**Warning signs:** `ValueError: Invalid isoformat string` during Google Drive ingestion.

### Pitfall 3: `modified_at` vs Content Hash Interaction
**What goes wrong:** A document's `modified_at` changes but content stays the same (e.g., metadata-only update on Google Drive). The content hash check at pipeline.py line 82 skips the document, so the new `modified_at` is never stored.
**Why it happens:** Content hash is computed from `raw_doc.content` bytes; `modified_at` is metadata.
**How to avoid:** This is acceptable behavior. If content hasn't changed, the graph edges are already correct. The `modified_at` on disk is irrelevant when content is identical. No special handling needed.
**Warning signs:** None -- this is correct behavior, not a bug.

### Pitfall 4: `getattr` Fallback Silently Hiding Bugs
**What goes wrong:** The current `getattr(raw_doc, "modified_at", None)` pattern silently returns `None` because `RawDocument` lacks the field. After adding the field, the `getattr` still works but is unnecessary.
**Why it happens:** Historical code from when `modified_at` was planned but not implemented.
**How to avoid:** Replace `getattr(raw_doc, "modified_at", None)` with direct `raw_doc.modified_at`. This makes missing fields a clear `AttributeError` instead of a silent fallback.

### Pitfall 5: Migration Sequence Number
**What goes wrong:** Alembic migration files must have sequential revision IDs and correct `down_revision` pointers.
**Why it happens:** Manual numbering. The latest is `006`.
**How to avoid:** New migration must be `007` with `down_revision = "006"`.

## Code Examples

### Adding `modified_at` to `RawDocument` (Pydantic)
```python
# src/pam/common/models.py - RawDocument class
class RawDocument(BaseModel):
    """Raw document content returned by connectors."""
    content: bytes
    content_type: str
    metadata: dict = Field(default_factory=dict)
    source_id: str
    title: str
    source_url: str | None = None
    owner: str | None = None
    modified_at: datetime | None = None  # NEW: document modification timestamp
```
Source: Direct codebase analysis of `/src/pam/common/models.py` line 232-240

### Adding `modified_at` to `Document` ORM Model
```python
# src/pam/common/models.py - Document class
class Document(Base):
    ...
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ...
```
Source: Pattern from existing `Document` model columns (e.g., `last_synced_at` at line 58)

### Markdown Connector -- Filesystem mtime
```python
# src/pam/ingestion/connectors/markdown.py
from datetime import UTC, datetime

async def fetch_document(self, source_id: str) -> RawDocument:
    path = Path(source_id).resolve()
    ...
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    return RawDocument(
        content=content,
        content_type="text/markdown",
        source_id=source_id,
        title=path.stem,
        source_url=f"file://{path}",
        modified_at=modified_at,
    )
```
Source: `pathlib.Path.stat()` stdlib docs + existing connector at `connectors/markdown.py` line 33-47

### Pipeline -- Direct Attribute Access
```python
# src/pam/ingestion/pipeline.py line 170 (replace getattr pattern)
reference_time=raw_doc.modified_at or datetime.now(UTC),
```
Source: Current code at `pipeline.py` line 170

### PostgresStore -- Persist `modified_at`
```python
# src/pam/ingestion/stores/postgres_store.py - upsert_document
async def upsert_document(
    self,
    ...,
    modified_at: datetime | None = None,  # NEW parameter
) -> uuid.UUID:
    stmt = insert(Document).values(
        ...,
        modified_at=modified_at,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_documents_source",
        set_={
            ...,
            "modified_at": stmt.excluded.modified_at,
        },
    )
```
Source: Existing `upsert_document` pattern at `postgres_store.py` line 20-58

### Sync-Graph Endpoint Fix
```python
# src/pam/api/routes/ingest.py line 195
reference_time=doc.modified_at or doc.last_synced_at or datetime.now(UTC),
```
Source: Current code at `ingest.py` line 195

### Graphiti Bi-temporal Confirmation
```python
# From graphiti_core/graphiti.py line 918 (inside add_episode):
# valid_at=reference_time
# This confirms: whatever we pass as reference_time becomes the edge's valid_at.
```
Source: Installed `graphiti_core` package at `.venv/.../graphiti_core/graphiti.py` line 918

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `getattr(raw_doc, "modified_at", None)` silently returns None | Direct `raw_doc.modified_at` attribute access | This phase | Correct bi-temporal timestamps on all edges |
| `last_synced_at` as sync-graph reference_time | `modified_at` with cascading fallback | This phase | Sync retry produces correct temporal edges |

**Deprecated/outdated:**
- `getattr(raw_doc, "modified_at", None)` pattern: Was a forward-compatible placeholder. After adding the field, replace with direct access.

## Scope & Affected Files Summary

| File | Change | Complexity |
|------|--------|------------|
| `src/pam/common/models.py` | Add `modified_at` to `RawDocument` Pydantic model + `Document` ORM model | Trivial |
| `alembic/versions/007_add_modified_at.py` | New migration adding nullable `modified_at` column | Trivial |
| `src/pam/ingestion/connectors/markdown.py` | Populate `modified_at` from `Path.stat().st_mtime` in both `fetch_document` and `list_documents` | Small |
| `src/pam/ingestion/connectors/google_docs.py` | Populate `modified_at` from Drive API `modifiedTime` field | Small |
| `src/pam/ingestion/connectors/google_sheets.py` | Populate `modified_at` from Drive API `modifiedTime` for both classes | Small |
| `src/pam/ingestion/stores/postgres_store.py` | Add `modified_at` parameter to `upsert_document()` | Trivial |
| `src/pam/ingestion/pipeline.py` | Replace `getattr` with direct access; pass `modified_at` to `upsert_document` | Trivial |
| `src/pam/api/routes/ingest.py` | Fix sync-graph endpoint to use `doc.modified_at` as primary reference_time | Trivial |
| `tests/test_ingestion/test_pipeline.py` | Update `RawDocument` fixtures to include `modified_at` | Small |

## Open Questions

1. **Google Sheets `modified_at` source**
   - What we know: The `spreadsheets().get()` API does not return `modifiedTime` directly. The Drive API `files().get()` does.
   - What's unclear: Whether `GoogleSheetsConnector.fetch_document()` should make an additional Drive API call for modification time.
   - Recommendation: Add a Drive API `files().get(fields="modifiedTime")` call inside `fetch_document()`. The extra API call is cheap (metadata only) and the connector already initializes a Drive API client via `_get_drive_service()`. For `LocalSheetsConnector` (test mock), leave `modified_at=None`.

2. **`DocumentInfo.modified_at` alignment with `RawDocument.modified_at`**
   - What we know: `DocumentInfo` already has `modified_at` (line 229), but `list_documents()` in `MarkdownConnector` hardcodes it to `None` (line 26).
   - What's unclear: Whether `list_documents()` should also populate `modified_at`. Currently only `fetch_document()` return value matters for ingestion.
   - Recommendation: Populate `modified_at` in `list_documents()` as well for consistency. It's a single `stat()` call per file, and the comment on line 26 literally says "Could use stat.st_mtime but keeping simple" -- this phase is the time to do it.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** - Direct reading of all affected files: `models.py`, `pipeline.py`, `extraction.py`, `markdown.py`, `google_docs.py`, `google_sheets.py`, `postgres_store.py`, `ingest.py`
- **Graphiti source** - `.venv/.../graphiti_core/graphiti.py` line 918 confirms `valid_at=reference_time` in `add_episode()`
- **Graphiti edge model** - `.venv/.../graphiti_core/edges.py` lines 274-279 confirms `valid_at` and `invalid_at` fields with descriptions

### Secondary (MEDIUM confidence)
- **Python stdlib docs** - `datetime.fromtimestamp(ts, tz=UTC)` for timezone-aware conversion from `st_mtime`
- **Google Drive API** - `modifiedTime` field available via `files.get()` and `files.list()` with field selector

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies, all existing project libraries
- Architecture: HIGH - Direct codebase analysis, clear data flow, every affected file read
- Pitfalls: HIGH - Timezone handling and migration numbering are well-understood from project patterns

**Research date:** 2026-02-22
**Valid until:** 2026-04-22 (60 days -- stable domain, no external API changes expected)
