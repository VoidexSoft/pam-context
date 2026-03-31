---
status: testing
phase: 13-lightrag-entity-and-relationship-vector-indices
source: 13-01-SUMMARY.md, 13-02-SUMMARY.md
started: 2026-02-24T16:00:00Z
updated: 2026-02-24T16:00:00Z
---

## Current Test

number: 1
name: VDB Indices Created on App Startup
expected: |
  When the app starts (docker compose up or uvicorn), the pam_entities and pam_relationships Elasticsearch indices are automatically created. Verify with: curl localhost:9200/_cat/indices?v — both indices should appear in the list.
awaiting: user response

## Tests

### 1. VDB Indices Created on App Startup
expected: When the app starts, pam_entities and pam_relationships ES indices are automatically created. Verify with: curl localhost:9200/_cat/indices?v — both indices should appear.
result: [pending]

### 2. Entities Indexed During Ingestion
expected: After ingesting a document that triggers graph extraction, the pam_entities index contains entity documents with embeddings. Verify with: curl localhost:9200/pam_entities/_count — count should be > 0.
result: [pending]

### 3. Relationships Indexed During Ingestion
expected: After ingesting a document, the pam_relationships index contains relationship documents with embeddings. Verify with: curl localhost:9200/pam_relationships/_count — count should be > 0.
result: [pending]

### 4. Smart Search Returns Entity Matches
expected: When querying the agent (or calling smart_search), the response includes an "Entity Matches" section listing entities with names, types, and descriptions found via vector similarity search.
result: [pending]

### 5. Smart Search Returns Relationship Matches
expected: When querying the agent (or calling smart_search), the response includes a "Relationship Matches" section listing relationships with source, target, keywords, and descriptions found via vector similarity search.
result: [pending]

### 6. 4-Way Concurrent Search Works End-to-End
expected: A single smart_search call returns results from all 4 sources: ES segments, Graphiti graph, entity VDB, and relationship VDB. The response should contain sections for each source that returned results. If any source is unavailable, the others still return results gracefully.
result: [pending]

### 7. Integration Tests Pass
expected: Running pytest tests/test_agent/test_smart_search_vdb.py passes all 13 tests covering VDB search methods, smart_search integration, graceful failure, and config defaults.
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0

## Gaps

[none yet]
