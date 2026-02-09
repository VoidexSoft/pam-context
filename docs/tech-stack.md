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
| Parsing | Embeddings | OpenAI `text-embedding-3-large` (3072 dims) | Proprietary API |
| Storage | Vector + BM25 | **Elasticsearch** 8.x | SSPL / Elastic License |
| Storage | Catalog & metadata | **PostgreSQL** 16 | PostgreSQL License |
| Storage | Knowledge graph | **Neo4j** 5.x Community + **Graphiti** | GPL (Community) / MIT |
| Storage | Cache | **Redis** 7.x | RSALv2 |
| Orchestration | Agent framework | **LangGraph** (LangChain) | MIT |
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

**Decision**: Elasticsearch provides vector + BM25 + filtering in one system. If RAGFlow is used alongside, it already expects Elasticsearch. Avoids multi-system fusion complexity.

### Neo4j + Graphiti (Knowledge Graph)

**Why Neo4j over alternatives:**

| Option | Pros | Cons |
|---|---|---|
| **Neo4j + Graphiti (chosen)** | Most mature graph DB, Graphiti adds bi-temporal model, large community | GPL license (Community), Java-heavy |
| TypeDB | Better schema enforcement, nested relationships | Smaller community, less LLM tooling |
| FalkorDB | Redis-compatible, fast | Less mature for knowledge graphs |
| Skip KG entirely | Simpler system | Lose "what changed and why" capability |

**Decision**: Neo4j is the most production-proven graph DB. Graphiti adds the temporal layer needed for tracking metric/definition evolution over time. Can be deferred to Phase 2.

### LangGraph (Agent Orchestration)

**Why LangGraph over alternatives:**

| Option | Pros | Cons |
|---|---|---|
| **LangGraph (chosen)** | State management, multi-step reasoning, human-in-the-loop, tool use | Learning curve, LangChain dependency |
| Claude Agent SDK | Native Claude integration, simpler | Less mature, fewer patterns |
| CrewAI | Multi-agent out of the box | Overkill for single-agent retrieval |
| Custom agent loop | Full control | Reinventing the wheel |

**Decision**: LangGraph provides the state machine and tool-use patterns needed for complex retrieval workflows (multi-hop reasoning, permission checks, citation assembly).

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

**Primary: OpenAI `text-embedding-3-large`**
- 3072 dimensions
- Best-in-class retrieval benchmarks
- Matryoshka support (can truncate to 1536 or 256 dims for cost savings)

**Alternative: Cohere `embed-v4`**
- Strong multilingual support
- Native int8/binary quantization

**Self-hosted alternative: `nomic-embed-text-v1.5`**
- Runs locally via Ollama
- 768 dimensions, good quality
- Zero API cost

---

## Infrastructure Requirements

### Development

```
Docker Compose:
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
| OpenAI embeddings (initial ingestion) | ~$50 |
| OpenAI embeddings (incremental) | ~$5/mo |
| Claude API (queries) | ~$200-500/mo |
| Cohere Rerank (optional) | ~$50/mo |
| **Total API costs** | **~$300-600/mo** |

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
