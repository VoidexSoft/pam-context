# PAM Context — Tech Stack

## Overview

This document details every technology choice, the rationale behind it, and alternatives considered.

---

## Core Stack Summary

| Layer | Component | Technology | License |
|---|---|---|---|
| Ingestion | Google connector | Google Drive API v3 + Sheets API v4 | - |
| Ingestion | File watcher | chokidar (Node.js) or watchdog (Python) | MIT |
| Parsing | Document parser | **Docling** (IBM / LF AI) | MIT |
| Parsing | Chunking | Docling HybridChunker | MIT |
| Parsing | Entity extraction | **LangExtract** (Google) — Phase 2 | Apache 2.0 |
| Parsing | Embeddings | OpenAI `text-embedding-3-large` (1536 dims via Matryoshka) | Proprietary API |
| Storage | Vector + BM25 | **Elasticsearch** 8.x (+ **Haystack 2.x** pipeline option) | SSPL / Elastic License + Apache 2.0 |
| Storage | Catalog & metadata | **PostgreSQL** 16 | PostgreSQL License |
| Storage | Knowledge graph | **Neo4j** 5.x Community + **Graphiti** | GPL (Community) / MIT |
| Storage | Cache | **Redis** 7.x (Phase 2+; in-memory caching for Phase 1) | RSALv2 |
| Retrieval | Pipeline framework | **Haystack** 2.x (`haystack-ai` + `elasticsearch-haystack`) | Apache 2.0 |
| Orchestration | Agent framework | **Claude Agent SDK** or **LangGraph** (evaluate in Phase 1) | MIT |
| Orchestration | Reranking | Cohere Rerank API or `cross-encoder/ms-marco-MiniLM-L-12-v2` | Proprietary / Apache 2.0 |
| LLM | Primary model | **Claude** (Sonnet 4.5 / Opus 4.6) | Proprietary API |
| Backend | API server | **FastAPI** (Python) | MIT |
| Frontend | Web UI | **React** 18 + TypeScript | MIT |
| Deployment | Containers | **Docker** + Docker Compose | Apache 2.0 |
| Deployment | Production | **Kubernetes** (optional) | Apache 2.0 |
| Language | Primary | **Python** 3.12+ | - |
| Language | Frontend | **TypeScript** 5.x | Apache 2.0 |

---

## Detailed Choices & Rationale

### Docling (Document Parsing)

**Why Docling over alternatives:**

| Feature | Docling | LlamaParse | Unstructured | RAGFlow built-in |
|---|---|---|---|---|
| Table accuracy | 97.9% | ~90% | ~92% | ~90% |
| Runs locally | Yes (CPU/GPU) | No (cloud API) | Partial | Yes |
| Cost | Free | $0.003/page | Free (OSS) / paid | Free |
| Hierarchical output | Excellent | Good | Good | Good |
| OCR | Built-in | Built-in | Built-in | Built-in |
| Framework integrations | LangChain, LlamaIndex, Haystack | LlamaIndex | LangChain | RAGFlow only |
| Governance | LF AI Foundation | LlamaIndex Inc | Unstructured Inc | InfiniFlow |

**Decision**: Docling gives best accuracy, runs free locally, and has the broadest integration surface.

### Elasticsearch (Hybrid Search)

**Why Elasticsearch over separate Vector DB + BM25:**

| Approach | Pros | Cons |
|---|---|---|
| **Elasticsearch (chosen)** | Native hybrid search, mature, one system to operate, RAGFlow default | SSPL license, heavier resource usage |
| Qdrant + separate BM25 | Best vector perf, open source | Two systems, need external RRF fusion |
| pgvector + pg_textsearch | Single Postgres, simplest ops | Limited vector perf at scale |
| Pinecone + Elasticsearch | Best managed vector + best BM25 | Two vendors, higher cost |

**Decision**: Elasticsearch provides vector + BM25 + filtering in one system. Avoids multi-system fusion complexity. For teams wanting even simpler Phase 1 ops, pgvector + pg_trgm is a viable stepping stone (migrate to ES when scaling demands it).

### Haystack 2.x (Retrieval Pipeline)

**Why Haystack as an optional retrieval backend:**

Haystack 2.x provides a component-based pipeline framework for building retrieval systems. It integrates natively with Elasticsearch via `elasticsearch-haystack` and provides:

- **`ElasticsearchBM25Retriever`** + **`ElasticsearchEmbeddingRetriever`** — pre-built components for BM25 and vector search
- **`DocumentJoiner`** — built-in RRF (Reciprocal Rank Fusion) for combining retrieval results
- **`TransformersSimilarityRanker`** — cross-encoder reranking as a pipeline component
- **Standardized `Document` model** — consistent data format across the retrieval stack

| Approach | Pros | Cons |
|---|---|---|
| **Custom ES queries (legacy)** | Full control, async-native, no extra deps | Manual RRF implementation, maintenance burden |
| **Haystack 2.x (added)** | Standardized components, easy to swap retrievers/rankers, community ecosystem | Sync pipeline (requires `run_in_executor`), extra dependency |

**Decision**: Both backends are available behind a config toggle (`USE_HAYSTACK_RETRIEVAL`). The legacy backend remains the default. Haystack provides a more composable pipeline for experimenting with different retrieval strategies. The ES index mapping was updated to nest metadata under `meta.*` for compatibility with both backends.

**Key files**:
- `src/pam/retrieval/haystack_search.py` — `HaystackSearchService` (drop-in replacement)
- `src/pam/common/haystack_adapter.py` — Type conversions between PAM and Haystack models
- `src/pam/api/deps.py` — Backend selection via config toggle

### Neo4j + Graphiti (Knowledge Graph)

**Why Neo4j over alternatives:**

| Option | Pros | Cons |
|---|---|---|
| **Neo4j + Graphiti (chosen)** | Most mature graph DB, Graphiti adds bi-temporal model, large community | GPL license (Community), Java-heavy |
| TypeDB | Better schema enforcement, nested relationships | Smaller community, less LLM tooling |
| FalkorDB | Redis-compatible, fast | Less mature for knowledge graphs |
| Skip KG entirely | Simpler system | Lose "what changed and why" capability |

**Decision**: Neo4j is the most production-proven graph DB. Graphiti adds the temporal layer needed for tracking metric/definition evolution over time. Can be deferred to Phase 2.

### Agent Orchestration

**Evaluate before committing:**

| Option | Pros | Cons |
|---|---|---|
| **Claude Agent SDK (recommended for Phase 1)** | Native Claude integration, simpler, less code, mature as of 2026 | Tied to Claude, fewer patterns for complex state machines |
| LangGraph | State management, multi-step reasoning, human-in-the-loop, LLM-agnostic | Steepest learning curve, LangChain dependency, over-engineered for single-agent |
| Simple tool-use loop | Full control, minimal dependencies, fastest to build | Manual state management, harder to extend |
| CrewAI | Multi-agent out of the box, intuitive role-based model | Overkill for single-agent retrieval |

**Decision**: For Phase 1's single-agent retrieval pattern (receive query → call tools → synthesize), **Claude Agent SDK or a simple tool-use loop** is likely sufficient and significantly simpler. The Claude Agent SDK has matured considerably through 2025-2026, with production adoption at scale. Reserve LangGraph for Phase 2+ if multi-agent workflows or complex state transitions become necessary.

### Claude (LLM)

**Why Claude over alternatives:**

- Strong reasoning and instruction following
- Excellent tool use capabilities
- Long context window (200K tokens)
- Good at structured output and citations
- Alternative: GPT-4o is comparable; system is LLM-agnostic at the agent layer

### FastAPI (Backend)

**Why FastAPI:**
- Native async support (essential for concurrent retrieval calls)
- Automatic OpenAPI docs
- Pydantic for request/response validation
- Python ecosystem aligns with Docling, LangGraph, LangExtract

### Embedding Model

**Primary: OpenAI `text-embedding-3-large` @ 1536 dims**
- Use Matryoshka truncation to 1536 dims (halves storage/compute, negligible quality loss)
- Full 3072 dims available if quality testing shows meaningful improvement
- MTEB score: 64.6

**Strong alternative: Cohere `embed-v4`**
- MTEB score: 65.2 (slightly outperforms OpenAI as of 2026 benchmarks)
- Designed to work in tandem with Cohere Rerank (which is already in the stack)
- Strong multilingual support
- Native int8/binary quantization

**Self-hosted alternative: `nomic-embed-text-v1.5` or `jina-embeddings-v4`**
- Runs locally via Ollama
- 768 dimensions (nomic) or configurable (jina)
- Zero API cost
- Jina v4 supports multimodal (text + images)

> **Important**: Build an abstracted embedding interface from Phase 1 so the model can be swapped without code changes. Run A/B comparisons on the evaluation set before committing.

---

## Infrastructure Requirements

### Development

```
Phase 1 (Docker Compose):
  - Elasticsearch: 4GB RAM
  - PostgreSQL: 1GB RAM
  - pam-api: 2GB RAM (Docling models loaded)
  - pam-web: 512MB RAM
  Total: ~7.5GB RAM minimum

Full Stack (Phase 3+):
  - Elasticsearch: 4GB RAM
  - PostgreSQL: 1GB RAM
  - Neo4j: 2GB RAM
  - Redis: 512MB RAM
  - pam-api: 2GB RAM (Docling models loaded)
  - pam-web: 512MB RAM
  Total: ~10GB RAM minimum
```

### Production (estimated for ~10K documents)

```
  - Elasticsearch: 3 nodes, 8GB RAM each
  - PostgreSQL: 1 node, 4GB RAM (RDS or equivalent)
  - Neo4j: 1 node, 8GB RAM
  - Redis: 1 node, 2GB RAM
  - API servers: 2 replicas, 4GB RAM each
  - Ingestion workers: 2 replicas, 4GB RAM each (GPU optional for Docling)
```

### API Costs (estimated monthly, 10K docs, 1K queries/day)

| Service | Estimated Cost |
|---|---|
| OpenAI embeddings (initial ingestion, 1536 dims) | ~$30 |
| OpenAI embeddings (incremental) | ~$5/mo |
| Claude API (queries — includes multi-tool calls per query) | ~$500-1,500/mo |
| Cohere Rerank (Phase 2+) | ~$50/mo |
| **Total API costs** | **~$600-1,600/mo** |

> **Note**: Claude costs are higher than naive estimates because each query typically involves 2-4 tool calls (search, graph lookup, SQL, synthesis), each consuming input/output tokens. Use **Sonnet 4.5 for simple lookups** and **Opus for complex multi-hop reasoning** to optimize costs. Monitor token usage per query from Phase 1.

---

## Key Dependencies (Python)

```
# Core
docling>=2.0
langchain>=0.3
langgraph>=0.2
langextract>=0.1

# Storage clients
elasticsearch>=8.0
haystack-ai>=2.0
elasticsearch-haystack>=1.0
psycopg[binary]>=3.0
neo4j>=5.0
redis>=5.0
graphiti-core>=0.5

# APIs
anthropic>=0.40
openai>=1.50
google-api-python-client>=2.0
google-auth-oauthlib>=1.0

# Server
fastapi>=0.115
uvicorn>=0.30
pydantic>=2.0

# Utilities
python-dotenv
structlog
tenacity
```
