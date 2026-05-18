# LanceDB Migration: Replace Elasticsearch + Haystack

**Date:** 2026-05-19
**Status:** Approved
**Related:** [2026-03-30 Universal Memory Layer Design](./2026-03-30-universal-memory-layer-design.md)

## Vision

Replace Elasticsearch and Haystack with LanceDB as PAM Context's sole vector and full-text search engine. Consolidate document chunks, memory embeddings, and glossary terms into LanceDB tables. Eliminate the ES container and Haystack pipeline dependencies. PostgreSQL keeps relational and transactional data; LanceDB owns all vector and FTS workloads.

## Motivation

- **Operational simplicity:** ES requires a JVM container, index lifecycle management, and dual maintenance with Haystack. LanceDB runs embedded inside the FastAPI process — zero external services.
- **Performance:** LanceDB outperforms ES on vector QPS and matches or beats it on FTS for the project's expected scale (single-node, <10M vectors initially).
- **Multimodal readiness:** Future phases (image-heavy ingestion, multimodal RAG) align with LanceDB's native multimodal lakehouse design.
- **Cost:** Disk-based, compute-storage separation makes scaling cheaper than memory-resident ES.
- **Single API:** Hybrid (BM25 + vector) lives in one query call — no RRF orchestration code in PAM.
- **Dev stage advantage:** No production data, no migration risk. Full rip-and-replace is feasible now and not later.

## Scope

### In scope

- Replace ES + Haystack with LanceDB for documents, memories, and glossary terms
- Embedded mode, file-based storage under `./data/lance/`
- Keep OpenAI embedder and cross-encoder reranker unchanged
- Schema mirrors current ES mapping with nested `meta` struct
- IVF_PQ index as default
- Phased PRs (5 total) for reviewability
- New Alembic migration to drop unused PG embedding columns
- Drop ES container from docker-compose, drop ES/Haystack deps from pyproject.toml

### Out of scope

- Graph storage (Neo4j/Graphiti unchanged)
- Cache (Redis unchanged)
- Analytics (DuckDB unchanged)
- LanceDB Cloud or server deployment (embedded only)
- Automatic embedding via Lance's embedding registry (manual via existing `OpenAIEmbedder`)
- Multimodal ingestion (deferred — schema leaves room, but no connectors yet)

## Architecture

### Storage layer

```
Before:
PG (relational + Memory.embedding) + ES (docs hybrid) + Neo4j (graph) + Redis + DuckDB

After:
PG (relational only) + LanceDB (all vectors + FTS) + Neo4j + Redis + DuckDB
```

### LanceDB tables

| Table | Purpose | Owner module |
|-------|---------|--------------|
| `documents` | Doc chunks with content, embedding, meta | `pam/retrieval/` |
| `memories` | Memory content + embeddings for dedup/recall | `pam/memory/` |
| `glossary` | Term canonical + aliases + embedding (Phase 4) | `pam/glossary/` |

### Deployment mode

- Embedded: `lancedb.connect(settings.lance_data_dir)`
- Default path: `./data/lance/` in dev, mounted volume in containerized prod
- Lives inside the FastAPI app process; no separate service or port
- Backup: filesystem snapshot of the data directory
- Disaster recovery: rebuild from PG source-of-truth via re-ingest pipeline

### Removed components

- Elasticsearch service from `docker-compose.yml` and `docker-compose.test.yml`
- `elasticsearch[async]`, `haystack-ai`, `elasticsearch-haystack` from `pyproject.toml`
- `src/pam/retrieval/haystack_search.py`
- `src/pam/retrieval/hybrid_search.py` (ES variant)
- `src/pam/common/haystack_adapter.py`
- ES index initialization scripts
- `USE_HAYSTACK_RETRIEVAL` config flag and all ES-related settings

### New components

- `src/pam/retrieval/lance_store.py` — connection, schema, table lifecycle
- `src/pam/retrieval/lance_search.py` — `SearchProtocol` implementation, hybrid query
- `src/pam/retrieval/lance_migrations.py` — schema versioning + evolution
- `src/pam/retrieval/lance_admin.py` — CLI for index rebuild and admin tasks
- `src/pam/memory/lance_store.py` — memory vector ops (dedup, recall)
- `src/pam/glossary/lance_store.py` — glossary embeddings + FTS on aliases (Phase 4)

### Cross-cutting (unchanged)

- OpenAI embedder (`text-embedding-3-small`, 1536 dims)
- `sentence-transformers` cross-encoder reranker
- Redis cache
- Structlog correlation IDs
- FastAPI dependency injection pattern

## Components

### `LanceStore` (`pam/retrieval/lance_store.py`)

Connection and table lifecycle.

- Holds `lancedb.AsyncConnection`
- Methods: `get_or_create_table(name, schema)`, `add(table, records)`, `delete_by_filter(table, where)`, `count(table)`
- Schema defined via `pyarrow.Schema` constants per table
- Singleton-per-process, injected via FastAPI `Depends`
- Initialized in FastAPI lifespan; tables created on first access

### `LanceSearchService` (`pam/retrieval/lance_search.py`)

Implements existing `SearchProtocol`.

- Hybrid query: `tbl.search((query_text, vector), query_type="hybrid").where(filter_clause).limit(top_k)`
- Filter clause built from `SearchQuery.filters` → Lance SQL syntax (e.g. `project_id = '...' AND meta.doc_type = 'pdf'`)
- Returns `list[SearchResult]` (same shape as today)
- Reranker invoked after Lance returns top-K (default 50) → final top-N (default 10)
- All existing retrieval consumers see no API change

### `MemoryService` refactor (`pam/memory/`)

- Drop `embedding` column from `Memory` ORM model (if pgvector ever used)
- `MemoryStore` (PG) keeps: `id, user_id, project_id, type, content, importance, access_count, timestamps, metadata`
- New `LanceMemoryStore` owns: dedup search, vector upsert, vector recall
- Dedup: cosine sim > 0.9 in Lance → fetch matched memory_id → `MemoryService._merge_and_update` updates PG row + Lance row
- Consistency model: PG = source of truth; Lance = derived index
- On Lance write failure: PG row marked `index_status='pending'` (new column on `documents`, `segments`, `memories`, `terms` tables — added via Alembic in PR3), background reconciler retries (later phase)

### Glossary on Lance (Phase 4 — adapts universal-memory-layer spec)

- `Term` PG row keeps: `id, project_id, canonical, aliases, definition, category, metadata, timestamps`
- `LanceGlossaryStore` owns: alias FTS, canonical embedding, fuzzy term matching
- Aliases stored as `list<string>` in Lance, tokenized for FTS match
- Resolve endpoint queries Lance first, falls back to PG ILIKE on canonical for exact matches

### Config additions (`pam/common/config.py`)

```python
lance_data_dir: Path = Path("./data/lance")
lance_documents_table: str = "documents"
lance_memories_table: str = "memories"
lance_glossary_table: str = "glossary"
lance_index_type: str = "IVF_PQ"
lance_num_partitions: int = 256
lance_num_sub_vectors: int = 96
lance_hybrid_top_k: int = 50
lance_rerank_top_n: int = 10
```

### Config removed

- `elasticsearch_url`, `elasticsearch_index`, `elasticsearch_username`, `elasticsearch_password`
- `use_haystack_retrieval`
- Any Haystack-specific tuning settings

### Ingestion pipeline (`pam/ingestion/pipeline.py`)

- Replace `es_store.add(...)` with `lance_store.add(table="documents", records=chunks)`
- PG `Document`/`Segment` writes unchanged
- Content hash dedup unchanged
- Embedding step unchanged (OpenAI embedder)

### Agent tools (`pam/agent/agent.py`)

- `search_knowledge` calls `LanceSearchService` instead of ES backend
- Tool signature, response shape, and JSON schema unchanged
- All 8 existing agent tools see no API change

### MCP server (`pam/mcp/`)

- `pam_search`, `pam_smart_search`, `pam_get_document`, and future memory/glossary tools route through new Lance-backed services
- No MCP tool API change

### Alembic migrations

- New migration: drop unused embedding columns from memory and glossary tables (if any exist)
- Drop pgvector extension if installed
- ES has no Alembic involvement, so nothing to remove there

## Data Flow

### Document ingestion

```
file → MarkdownConnector → Docling parse → HybridChunker → OpenAIEmbedder
  → PG: insert Document + Segment rows (relational)
  → Lance documents table: {id, doc_id, segment_id, content, embedding,
     meta{source, doc_type, project_id, tags, created_at}}
  → return IngestResult
```

### Document search

```
SearchQuery(query, filters={project_id, doc_type})
  → OpenAIEmbedder.embed_query → vector[1536]
  → LanceSearchService.search:
      tbl.search((query, vector), query_type="hybrid")
         .where("project_id = '...' AND meta.doc_type = 'pdf'")
         .limit(50)
  → list[LanceRow]
  → Reranker(cross-encoder) → top-10
  → list[SearchResult]
```

### Memory write

```
POST /api/memory {user_id, content, type}
  → embed content
  → LanceMemoryStore.search_dedup(embedding, threshold=0.9, user_id)
      → if match: MemoryService._merge_and_update
          → LLM merge content
          → PG update Memory row (content, updated_at)
          → Lance upsert row (new embedding)
      → else: insert
          → PG insert Memory row
          → Lance insert row
  → return MemoryResponse
```

### Memory recall

```
GET /api/memory/search?q=...&user_id=...
  → embed query
  → Lance memories table: hybrid search, filter user_id
  → top-K rows → join PG by memory_id for fresh importance/access_count
  → update PG access_count, last_accessed_at
  → return MemorySearchResult[]
```

### Glossary resolve (Phase 4)

```
POST /api/glossary/resolve {query}
  → tokenize → candidate terms
  → for each candidate:
      → Lance glossary FTS on aliases list
      → if no FTS hit, vector search on embedding
  → return {original, canonical, confidence}
```

### Consistency model

- PG is source of truth for relational identity (Document, Segment, Memory, Term)
- Lance is a derived index (vectors + FTS)
- Writes: PG first, then Lance. On Lance failure: log + mark PG row `index_status='pending'`
- Reads: Lance for search and filter; PG for full row hydration when transactional fields are needed (memory access counters, glossary metadata)
- Background reconciler (later phase) scans `index_pending` rows and reindexes

## Schema

### `documents` table

```python
import pyarrow as pa

DOCUMENTS_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("doc_id", pa.string(), nullable=False),
    pa.field("segment_id", pa.string(), nullable=False),
    pa.field("content", pa.string(), nullable=False),
    pa.field("embedding", pa.list_(pa.float32(), 1536), nullable=False),
    pa.field("meta", pa.struct([
        pa.field("source", pa.string()),
        pa.field("doc_type", pa.string()),
        pa.field("project_id", pa.string()),
        pa.field("tags", pa.list_(pa.string())),
        pa.field("created_at", pa.timestamp("us", tz="UTC")),
        pa.field("content_hash", pa.string()),
    ])),
])
```

Indexes: IVF_PQ on `embedding`, FTS on `content`, scalar indexes on `meta.project_id`, `meta.doc_type`.

### `memories` table

```python
MEMORIES_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("user_id", pa.string(), nullable=False),
    pa.field("project_id", pa.string(), nullable=False),
    pa.field("type", pa.string(), nullable=False),
    pa.field("content", pa.string(), nullable=False),
    pa.field("embedding", pa.list_(pa.float32(), 1536), nullable=False),
    pa.field("importance", pa.float32()),
    pa.field("created_at", pa.timestamp("us", tz="UTC")),
])
```

Indexes: IVF_PQ on `embedding`, FTS on `content`, scalar indexes on `user_id`, `project_id`, `type`.

### `glossary` table (Phase 4)

```python
GLOSSARY_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("project_id", pa.string(), nullable=False),
    pa.field("canonical", pa.string(), nullable=False),
    pa.field("aliases", pa.list_(pa.string()), nullable=False),
    pa.field("definition", pa.string()),
    pa.field("category", pa.string()),
    pa.field("embedding", pa.list_(pa.float32(), 1536), nullable=False),
])
```

Indexes: IVF_PQ on `embedding`, FTS on `aliases` and `canonical`, scalar index on `project_id`.

## Error Handling

### Connection errors

- Startup: `lance_store.connect()` runs in FastAPI lifespan. Fail fast if data dir unwritable or corrupted.
- Runtime: wrap Lance ops in try/except, raise `SearchBackendError` (existing exception type).
- `/health` endpoint checks Lance connection and table count.

### Write failures (PG ok, Lance fails)

- Log structured error with `correlation_id`, `doc_id`/`memory_id`.
- Mark PG row `index_status='pending'` (new column on Document, Segment, Memory, Term — added via Alembic in PR3 alongside the embedding column drop).
- Return success to caller (relational write succeeded).
- Background reconciler (later phase) reindexes pending rows.
- Metric: `lance_write_failures_total` counter.

### Write failures (PG fails)

- Lance not touched (PG attempted first).
- Standard FastAPI exception handler returns 500.

### Search failures

- Lance timeout or error → log + raise `SearchBackendError`.
- API returns 503 with `Retry-After`.
- No silent fallback. Errors surface per project convention.

### Dedup edge cases

- Multiple candidates above 0.9 threshold → pick highest similarity, log warning with all matches.
- LLM merge fails → keep old content, log warning, alert.

### Schema migrations

- Lance schema evolution via `tbl.add_columns()` (Lance native).
- Code-managed migration script in `pam/retrieval/lance_migrations.py`.
- Versioned: `_lance_schema_version` metadata table tracks applied migrations.
- Run at app startup, idempotent.

### Index rebuild

- Manual CLI: `python -m pam.retrieval.lance_admin rebuild-index --table=documents`.
- Triggered when index type changes or recall degrades.
- Drops old index, creates new with current config.

### Recovery from corruption

- Lance data dir is self-contained; copy/restore semantics.
- Backup: filesystem snapshot or `cp -r`.
- Disaster recovery: rebuild Lance tables from PG source-of-truth via re-ingest pipeline.

## Testing

### Unit tests

- `tests/retrieval/test_lance_store.py` — table create, schema validation, add/delete/count.
- `tests/retrieval/test_lance_search.py` — hybrid query, filter clauses, reranker integration.
- `tests/memory/test_lance_memory.py` — dedup threshold, vector upsert.
- Fixture: `tmp_path` per-test, fresh `lancedb.connect(tmp_path)`.
- No mocks — Lance embedded is fast enough.

### Integration tests

- `tests/integration/test_ingestion_to_search.py` — full pipeline: parse → embed → Lance → search → verify hit.
- `tests/integration/test_memory_dedup.py` — store similar memory twice → merge invoked.
- Real PG (testcontainers or docker-compose), real Lance (tmp dir).
- Drop ES service from `docker-compose.test.yml`.

### Eval suite (`eval/run_eval.py`)

- Same `questions.json` and `judges.py`.
- Backend swapped: searches Lance instead of ES.
- Compare recall@10, precision@5, latency vs ES baseline (captured before migration).
- Acceptance criteria: recall and precision ≥ ES baseline; latency within 20% (or better).

### Performance tests

- `eval/bench_search.py` measures p50/p95/p99 latency and QPS.
- Existing Locust scenario unchanged; endpoint backend swapped.

### Migration verification (per PR)

- PR1: Lance store builds, schema applies, tests pass alongside ES.
- PR2: Ingestion writes to Lance; content matches PG segment count.
- PR3: Search results from Lance vs ES side-by-side comparison via eval suite.
- PR4: Memory dedup works; embedding column dropped from PG.
- PR5: ES container removed, deps removed, all tests green.

### CI changes

- Remove ES service from CI docker-compose.
- Add Lance data dir to `.gitignore` patterns.
- Optional: cache Lance test fixtures across runs for speedup.

## Phased Delivery

No production data exists, so the migration is rip-and-replace rather than dual-write. PRs are sequenced to keep each commit green and reviewable, not to support a transitional dual-backend state.

| PR | Scope | Acceptance |
|----|-------|------------|
| **PR1** — Lance scaffolding | Add LanceDB dep, `LanceStore`, `LanceSearchService` implementing `SearchProtocol`, schema modules, `lance_migrations.py`. Unit tests only — not yet wired into ingestion or API. | New code has full test coverage. ES path unchanged. App still runs on ES. |
| **PR2** — Switch ingestion + search to Lance | Pipeline writes to Lance (ES writes removed). Agent tools and FastAPI search routes read from Lance. ES code paths bypassed but files not yet deleted. Run eval suite against Lance. | Integration tests green. Eval recall/precision ≥ ES baseline captured before migration. |
| **PR3** — Memory migration | Move memory embeddings to Lance via `LanceMemoryStore`. Refactor `MemoryService` to call Lance for dedup/recall. Alembic migration drops unused PG embedding columns. | Memory tests green. Dedup behavior matches spec. PG schema clean. |
| **PR4** — Glossary on Lance (Phase 4 prerequisite) | Add `LanceGlossaryStore`. Wire glossary resolve endpoint through Lance. | Glossary tests green. Resolve endpoint returns canonical terms. |
| **PR5** — ES + Haystack removal | Delete ES container from docker-compose, drop deps from `pyproject.toml`, remove `hybrid_search.py`, `haystack_search.py`, `haystack_adapter.py`, ES config keys, ES test helpers. | All tests green. `docker-compose.yml` no longer references ES. `pyproject.toml` trimmed. CI ES service removed. |

Each PR ships green and is independently reviewable. PR2 is the functional cutover; PR5 is final cleanup.

## Design Principles

- **Embedded, no new infra:** LanceDB lives inside the FastAPI process. One fewer container to operate.
- **PG = relational, Lance = vectors:** Clean separation of concerns. PG remains the source of truth; Lance is a derived index.
- **Schema parity with ES:** Same nested `meta` struct keeps the migration straightforward and preserves query semantics.
- **Existing reranker reused:** Cross-encoder stays on top of Lance hybrid results — no quality regression.
- **No silent fallbacks:** Errors surface; pending writes are explicitly marked and retried.
- **Phased PRs:** Each PR ships green and is independently reviewable. PR3 is the cutover; PR5 is cleanup.
- **Existing patterns:** Pydantic Settings, SQLAlchemy, FastAPI DI, structlog correlation IDs — all preserved.
- **Backward compatible API:** All FastAPI routes, MCP tools, and agent tool signatures unchanged.
