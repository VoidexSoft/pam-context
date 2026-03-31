---
status: testing
phase: 07-ingestion-pipeline-extension-diff-engine
source: 07-01-SUMMARY.md, 07-02-SUMMARY.md
started: 2026-02-20T13:45:00Z
updated: 2026-02-20T13:45:00Z
---

## Current Test

number: 1
name: Database Migration — graph_synced columns exist
expected: |
  Documents table has `graph_synced` (boolean, default false) and `graph_sync_retries` (integer, default 0) columns.
  Run: `docker exec pam-postgres psql -U pam -d pam -c "\d documents"` — both columns should appear.
awaiting: user response

## Tests

### 1. Database Migration — graph_synced columns exist
expected: Documents table has `graph_synced` (boolean) and `graph_sync_retries` (integer) columns. Verify via psql \d documents.
result: [pending]

### 2. Document API includes graph_synced field
expected: GET /api/documents returns documents with a `graph_synced` field in the response JSON.
result: [pending]

### 3. Ingest folder triggers graph extraction
expected: Ingesting a folder via POST /api/ingest/folder produces documents. If Neo4j is running, graph_synced=true. If Neo4j is down, graph_synced=false (non-blocking — PG/ES data is still saved).
result: [pending]

### 4. Skip graph parameter on ingest
expected: POST /api/ingest/folder?skip_graph=true ingests documents normally but skips graph extraction entirely. Documents show graph_synced=false.
result: [pending]

### 5. Sync Graph button on Admin Dashboard
expected: Admin Dashboard shows a "Sync Graph" card/panel with a button. Clicking it triggers sync and shows loading spinner, then result counts (synced/failed/remaining) or an error message.
result: [pending]

### 6. Sync Graph API endpoint
expected: POST /api/ingest/sync-graph retries graph extraction for documents with graph_synced=false. Returns JSON with synced[], failed[], and remaining count.
result: [pending]

### 7. Re-ingestion uses chunk diff
expected: Re-ingesting the same folder a second time uses the diff engine — only changed/new chunks get graph extraction. Logs should show diff-related messages (added/removed/unchanged chunks).
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0

## Gaps

[none yet]
