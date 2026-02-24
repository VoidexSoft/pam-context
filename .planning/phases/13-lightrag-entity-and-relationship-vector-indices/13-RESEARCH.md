# Phase 13: Entity & Relationship Vector Indices - Research

**Researched:** 2026-02-24
**Domain:** Elasticsearch dense_vector indices for entity/relationship embeddings + ingestion pipeline integration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Entity embedding text: `"{name}\n{description}"` (LightRAG format)
- Relationship embedding text: `"{keywords}\t{src_entity}\n{tgt_entity}\n{description}"` (LightRAG format)
- entity_type stored as ES metadata field for filtering, NOT included in embedding text
- Embed all entities/relationships regardless of description length -- even short descriptions have semantic value for name-based discovery
- Use the same embedder configured for chunks (text-embedding-3-small, 1536-dim) -- reuse existing BaseEmbedder infrastructure
- Entity upsert: Use entity name as ES document ID -- re-ingestion overwrites with updated description + re-embedded vector
- Relationship upsert: ES document ID = `"{sorted_src}::{rel_type}::{sorted_tgt}"` -- allows multiple relationships between the same entity pair
- Index creation: Auto-create with mapping on first ingestion if index doesn't exist (same pattern as `pam_segments`)
- Orphan cleanup: Track `source_ids` per entity/relationship. When all source documents are removed, delete the orphaned entity/relationship from ES
- Entity/relationship VDB results returned as distinct result types (e.g., `source='entity_vdb'`, `source='relationship_vdb'`) -- agent sees them differently from document chunks
- All 4 searches (ES segments, Graphiti, entity VDB, relationship VDB) run concurrently via asyncio.gather
- Default: top 5 entities and top 5 relationships per search
- Entity embeddings batched together, relationship embeddings batched together -- separate from chunk embedding batches
- Skip re-embedding unchanged descriptions: hash embedding text content, compare against existing ES record hash, skip API call if unchanged
- No toggle to disable entity/relationship embedding -- always runs when graph extraction is enabled
- Log embedding count and latency via structlog (consistent with existing ingestion logging)

### Claude's Discretion
- Merge/ranking strategy for 4-way search results in smart_search
- Exact ES index mapping details (analyzer, similarity function)
- Batch size for embedding API calls
- Hash algorithm for change detection (SHA-256 consistent with existing content hashing)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VDB-01 | ES index `pam_entities` stores entity records with fields: `name`, `entity_type`, `description`, `embedding` (1536-dim), `source_ids`, `file_paths` | Architecture Pattern 1 (entity index mapping). Uses `dense_vector` with cosine similarity, same as existing `pam_segments`. Auto-created via `ensure_index()` pattern from `ElasticsearchStore`. |
| VDB-02 | ES index `pam_relationships` stores relationship records with fields: `src_entity`, `tgt_entity`, `keywords`, `description`, `embedding` (1536-dim), `weight`, `source_ids` | Architecture Pattern 2 (relationship index mapping). Same dense_vector pattern. Doc ID = `sorted_src::rel_type::sorted_tgt` for deterministic upsert. |
| VDB-03 | During graph extraction, entity and relationship descriptions are embedded and upserted into these indices alongside the existing Neo4j writes | Architecture Pattern 3 (extraction integration). After `add_episode()`, collect entities from `result.nodes` and relationships from `result.edges`, batch embed, and bulk upsert to ES. Pattern 4 (smart_search integration) handles the search side. |
</phase_requirements>

## Summary

Phase 13 creates two new Elasticsearch indices (`pam_entities` and `pam_relationships`) that store vector embeddings of entity and relationship descriptions from the knowledge graph. This follows LightRAG's 3-VDB architecture where `pam_segments` (chunks), `pam_entities`, and `pam_relationships` each provide a different semantic search perspective. Entity discovery enables queries like "find teams working on deployment" without exact entity names, while relationship discovery enables "what connects infrastructure to reliability" without knowing specific edge types.

The implementation has two integration points: (1) during ingestion, after `extract_graph_for_document()` produces entity nodes and relationship edges via Graphiti's `add_episode()`, the entity/relationship descriptions are embedded using the existing `BaseEmbedder` infrastructure and upserted into the new ES indices; (2) during retrieval, `smart_search` adds entity VDB and relationship VDB searches alongside the existing ES segment search and Graphiti graph search, running all four concurrently via `asyncio.gather`.

All building blocks exist: the `ElasticsearchStore` pattern for index creation and bulk upsert, the `OpenAIEmbedder` for embedding text, the `extract_graph_for_document()` return value (`AddEpisodeResults`) which includes `nodes: list[EntityNode]` and `edges: list[EntityEdge]` with `name`, `summary`/`fact`, and `labels` fields, and the `_smart_search()` handler in `agent.py` which already uses `asyncio.gather` for concurrent search.

**Primary recommendation:** Create a new `EntityRelationshipVDBStore` class in `src/pam/ingestion/stores/` following the `ElasticsearchStore` pattern, integrate it into `extract_graph_for_document()` to upsert entity/relationship embeddings after each `add_episode()` call, and extend `_smart_search()` to run 4-way concurrent search. Use SHA-256 hashing of embedding text content to skip re-embedding unchanged descriptions.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| elasticsearch (AsyncElasticsearch) | 8.19.3 (installed) | Entity and relationship VDB index storage and kNN search | Project standard for all ES operations |
| OpenAIEmbedder (BaseEmbedder) | Already in project | Embed entity/relationship description text into 1536-dim vectors | Project standard embedding model; reuse means no new API key/config |
| asyncio | stdlib | 4-way concurrent search in smart_search | Already used for 2-way concurrent search in Phase 12 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | Already installed | Log embedding count, latency, upsert operations | All logging in this phase |
| hashlib | stdlib | SHA-256 hash of embedding text for change detection | Skip re-embedding when descriptions unchanged |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ES dense_vector for VDB | Dedicated vector DB (Pinecone, Weaviate) | ES already runs in docker-compose, no new infra; ES 8.x kNN is production-grade for this scale |
| Embedding during extraction | Batch embedding in post-processing step | User decision: embed alongside Neo4j writes for simplicity. Slight latency increase per ingestion but keeps data consistent |
| Separate ES indices for entities/relationships | Single index with type discriminator field | Separate indices are cleaner for mapping, don't mix entity and relationship field schemas, easier to manage |

**Installation:**
No new packages needed. All dependencies are already in the project.

## Architecture Patterns

### Recommended Project Structure
```
src/pam/
├── ingestion/
│   └── stores/
│       ├── elasticsearch_store.py      # Existing (unchanged)
│       └── entity_relationship_store.py # NEW: Entity/Relationship VDB store
├── graph/
│   └── extraction.py                   # MODIFIED: Add VDB upsert after add_episode()
├── agent/
│   └── agent.py                        # MODIFIED: Extend _smart_search() for 4-way search
└── common/
    └── config.py                       # MODIFIED: Add entity/relationship index names + search limits
```

### Pattern 1: Entity VDB Index Mapping
**What:** ES index mapping for `pam_entities` with dense_vector embedding, keyword fields for name/type/source_ids, and text field for description.
**When to use:** Auto-created on first ingestion via `ensure_index()`.

```python
def get_entity_index_mapping(embedding_dims: int) -> dict:
    return {
        "mappings": {
            "properties": {
                "name": {"type": "keyword"},
                "entity_type": {"type": "keyword"},
                "description": {"type": "text", "analyzer": "standard"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "content_hash": {"type": "keyword"},
                "source_ids": {"type": "keyword"},  # array of doc source_ids
                "file_paths": {"type": "keyword"},   # array of file paths
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }
```

**Key design points:**
- `name` as `keyword` (not text) for exact match filtering and use as ES document ID
- `entity_type` as `keyword` for filtering (e.g., show only "Team" entities)
- `description` as `text` for BM25 fallback search alongside kNN
- `source_ids` as `keyword` array -- tracks which documents contributed this entity. When all source docs are removed, the entity can be orphan-cleaned
- `content_hash` as `keyword` -- SHA-256 of the embedding text (`"{name}\n{description}"`), used to skip re-embedding when description hasn't changed
- `embedding` as `dense_vector` with cosine similarity, same config as `pam_segments`

### Pattern 2: Relationship VDB Index Mapping
**What:** ES index mapping for `pam_relationships` with dense_vector embedding and relationship-specific fields.
**When to use:** Auto-created on first ingestion via `ensure_index()`.

```python
def get_relationship_index_mapping(embedding_dims: int) -> dict:
    return {
        "mappings": {
            "properties": {
                "src_entity": {"type": "keyword"},
                "tgt_entity": {"type": "keyword"},
                "keywords": {"type": "text", "analyzer": "standard"},
                "description": {"type": "text", "analyzer": "standard"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "content_hash": {"type": "keyword"},
                "weight": {"type": "float"},
                "source_ids": {"type": "keyword"},
                "rel_type": {"type": "keyword"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }
```

**Key design points:**
- ES document ID = `"{sorted_src}::{rel_type}::{sorted_tgt}"` (per user decision) -- allows multiple relationship types between same entity pair (e.g., A MANAGES B and A MENTORS B)
- `sorted_src/sorted_tgt` means alphabetically sorted to ensure A::REL::B == B::REL::A for undirected relationships
- `weight` tracks relationship strength/frequency (from Graphiti edge data or count of episodes)
- `keywords` stored as text for BM25 matching alongside kNN
- `content_hash` of embedding text `"{keywords}\t{src}\n{tgt}\n{description}"` for skip-re-embedding

### Pattern 3: VDB Upsert During Graph Extraction
**What:** After each `add_episode()` call in `extract_graph_for_document()`, collect entity and relationship data from the result, embed descriptions, and upsert to ES indices.
**When to use:** During the graph extraction step of the ingestion pipeline.

**Critical insight -- Graphiti `AddEpisodeResults` provides:**
- `result.nodes: list[EntityNode]` -- each has `name: str`, `summary: str`, `labels: list[str]`, `uuid: str`
- `result.edges: list[EntityEdge]` -- each has `name: str` (rel type), `fact: str` (description), `source_node_uuid: str`, `target_node_uuid: str`, `episodes: list[str]`

**Challenge: resolving edge UUIDs to entity names.**
EntityEdge gives `source_node_uuid` and `target_node_uuid`, not entity names. We need to build a UUID-to-name map from the nodes returned by `add_episode()`.

**Solution:**
```python
# Build UUID -> name map from all nodes we've seen
entity_map: dict[str, str] = {}  # uuid -> name
for node in episode_result.nodes:
    entity_map[node.uuid] = node.name

# For edges, resolve UUIDs to names
for edge in episode_result.edges:
    src_name = entity_map.get(edge.source_node_uuid, edge.source_node_uuid)
    tgt_name = entity_map.get(edge.target_node_uuid, edge.target_node_uuid)
```

**Accumulation pattern:** Entities and relationships accumulate across all chunks of a document. After processing all chunks, batch-embed and bulk-upsert once per document (not per chunk) to minimize API calls.

```python
# Accumulate across all chunks
all_entities: dict[str, EntityVDBRecord] = {}   # name -> record
all_relationships: dict[str, RelVDBRecord] = {}  # sorted_key -> record

for chunk in diff.added:
    result = await graph_service.client.add_episode(...)
    for node in result.nodes:
        all_entities[node.name] = EntityVDBRecord(
            name=node.name,
            entity_type=_extract_type(node.labels),
            description=node.summary,
        )
    for edge in result.edges:
        src = entity_map.get(edge.source_node_uuid, "")
        tgt = entity_map.get(edge.target_node_uuid, "")
        key = _make_rel_key(src, edge.name, tgt)
        all_relationships[key] = RelVDBRecord(
            src_entity=src, tgt_entity=tgt,
            rel_type=edge.name, description=edge.fact,
        )

# After all chunks: batch embed + bulk upsert
await vdb_store.upsert_entities(list(all_entities.values()), embedder, source_id)
await vdb_store.upsert_relationships(list(all_relationships.values()), embedder, source_id)
```

### Pattern 4: 4-Way Concurrent Search in smart_search
**What:** Extend `_smart_search()` to run ES segments, Graphiti, entity VDB, and relationship VDB searches concurrently.
**When to use:** Every `smart_search` tool call.

```python
# Inside _smart_search()
es_result, graph_result, entity_result, rel_result = await asyncio.gather(
    _es_search_coro(),
    _graph_search_coro(),
    _entity_vdb_search_coro(),       # NEW
    _relationship_vdb_search_coro(),  # NEW
    return_exceptions=True,
)
```

**Entity VDB search pattern:**
- Query text: join low-level keywords (same as ES segment search)
- Embed query text, run kNN search on `pam_entities` index
- Return entity name, type, description, relevance score

**Relationship VDB search pattern:**
- Query text: join high-level keywords (same as Graphiti search)
- Embed query text, run kNN search on `pam_relationships` index
- Return src_entity, tgt_entity, rel_type, description, relevance score

**kNN search query structure (ES 8.x):**
```python
body = {
    "knn": {
        "field": "embedding",
        "query_vector": query_embedding,
        "k": top_k,
        "num_candidates": top_k * 10,
    },
    "size": top_k,
    "_source": {"excludes": ["embedding"]},
}
response = await es_client.search(index="pam_entities", body=body)
```

**Result formatting:** Entity and relationship VDB results are formatted as distinct sections in the output, separate from document results and graph results:
```
## Entity Matches (from vector index)
- [Entity] AuthService (Technology): Handles authentication and authorization...

## Relationship Matches (from vector index)
- [Relationship] AuthService -> PaymentModule (DEPENDS_ON): The authentication service validates tokens...
```

### Pattern 5: Orphan Cleanup via source_ids Tracking
**What:** Each entity/relationship in ES tracks which document `source_ids` contributed to it. When a document is fully removed, its source_id is removed from the arrays. Entities/relationships with empty `source_ids` are orphans and can be deleted.
**When to use:** During re-ingestion or document deletion.

**Implementation approach:**
- On upsert: merge the current `source_id` into the existing `source_ids` array via ES partial update (or full overwrite)
- On document deletion: use ES `update_by_query` to remove the source_id from all entity/relationship records, then delete any records with empty `source_ids`
- This can be a separate cleanup step, not blocking the main ingestion flow

### Anti-Patterns to Avoid
- **Embedding per-chunk instead of per-document:** Entity descriptions evolve across chunks as Graphiti merges node summaries. Embedding per-chunk creates duplicate/stale entries. Accumulate all entities/relationships across chunks, then embed once per document at the end.
- **Using entity UUID as ES doc ID:** UUIDs are Graphiti-internal and change between ingestions. Entity `name` is the stable identifier (per user decision).
- **Mixing entity and relationship records in a single index:** Different field schemas (entities have `entity_type`, relationships have `src_entity`/`tgt_entity`/`weight`). Separate indices are cleaner.
- **Re-embedding all entities on every ingestion:** Hash the embedding text content and compare against the stored `content_hash`. Only embed when the description actually changed.
- **Sequential search in smart_search:** All 4 searches are independent -- always use `asyncio.gather` with `return_exceptions=True`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ES index creation + mapping | Custom mapping logic | Follow `ElasticsearchStore.ensure_index()` pattern | Proven auto-create-if-not-exists pattern |
| Text embedding | Custom embedding service | Reuse `BaseEmbedder` / `OpenAIEmbedder` with `embed_texts()` | Handles batching, retries, caching, cost tracking |
| Content change detection | Custom diff engine | SHA-256 hash of embedding text (same as `content_hash` in ingestion) | Project-standard pattern, simple and reliable |
| Bulk ES operations | Individual ES index calls | ES `bulk()` API via `client.bulk(operations=...)` | 10-100x faster than individual index calls |
| kNN vector search | Custom similarity computation | ES `knn` query | Hardware-optimized HNSW index built into ES 8.x |

**Key insight:** This phase is primarily integration work connecting existing building blocks. The entity/relationship data comes from Graphiti, embedding comes from OpenAIEmbedder, storage comes from ES, and search comes from ES kNN queries. The new code is the glue: a VDB store class, extraction integration, and search integration.

## Common Pitfalls

### Pitfall 1: Entity UUID-to-Name Resolution Across Chunks
**What goes wrong:** `EntityEdge.source_node_uuid` and `target_node_uuid` are UUIDs, not entity names. If the entity was created in a previous chunk's `add_episode()` call, its UUID is not in the current result's `nodes` list.
**Why it happens:** Graphiti reuses existing entity nodes across episodes. The same entity might be mentioned in chunk 1 and chunk 5, but the EntityEdge in chunk 5 only references the UUID created during chunk 1.
**How to avoid:** Build a cumulative `uuid_to_name: dict[str, str]` map across all chunks during extraction. After each `add_episode()`, add all returned nodes to the map. When processing edges, look up names from the cumulative map. As a fallback, query Neo4j for the entity name by UUID if not found in the map.
**Warning signs:** Relationship VDB entries have UUIDs instead of entity names in `src_entity` or `tgt_entity` fields.

### Pitfall 2: Empty Entity Summaries from Graphiti
**What goes wrong:** Some `EntityNode.summary` fields may be empty strings, especially for entities mentioned briefly or ambiguously in text.
**Why it happens:** Graphiti generates summaries on a best-effort basis. Short or unclear mentions may not produce meaningful summaries.
**How to avoid:** Per user decision, embed all entities regardless of description length. For empty summaries, the embedding text is just `"{name}\n"` which still provides semantic value for name-based discovery. Log a warning for empty summaries but do not skip them.
**Warning signs:** kNN search on entity VDB returns entities with empty descriptions ranked highly.

### Pitfall 3: Stale Entities After Re-ingestion
**What goes wrong:** When a document is re-ingested and an entity is no longer mentioned, its VDB entry persists with the old source_id, creating phantom entities.
**Why it happens:** Graphiti handles entity lifecycle in Neo4j, but ES indices are unaware of Neo4j deletions.
**How to avoid:** On re-ingestion, the new extraction replaces the entity's description (via upsert by name). Orphan cleanup handles entities whose source documents are fully removed. For the case where re-ingestion no longer mentions an entity: the entity persists from other documents or the orphan cleanup eventually removes it.
**Warning signs:** Entity count in ES grows monotonically even when documents are updated to remove references to entities.

### Pitfall 4: Embedding API Cost During Large Ingestion
**What goes wrong:** Ingesting many documents creates hundreds of entities/relationships, each needing an embedding API call, significantly increasing cost and latency.
**Why it happens:** Each unique entity description needs a 1536-dim embedding from OpenAI.
**How to avoid:** (1) Accumulate entities/relationships across all chunks, deduplicate by name/key, then batch-embed all unique descriptions in one API call per document. (2) Use `content_hash` to skip re-embedding unchanged descriptions. (3) Use the same `embed_texts()` batch method that handles automatic chunking at `BATCH_SIZE=100`.
**Warning signs:** Ingestion latency increases 3-5x after enabling entity/relationship embedding.

### Pitfall 5: 4-Way asyncio.gather Exception Handling
**What goes wrong:** One failing search (e.g., ES index not yet created) causes that coroutine to return an Exception object, which is passed to the agent as raw text if not checked.
**Why it happens:** `return_exceptions=True` returns Exception objects instead of raising them. If not checked with `isinstance(result, Exception)`, the exception is treated as a valid result.
**How to avoid:** Check each of the 4 results with `isinstance(result, Exception)` and set appropriate defaults (empty list) plus warning messages. This is already done for the 2-way case in Phase 12 -- extend the same pattern.
**Warning signs:** Agent receives "TypeError" or traceback text in search results.

## Code Examples

### Entity/Relationship VDB Store Class
```python
# src/pam/ingestion/stores/entity_relationship_store.py
import hashlib
from dataclasses import dataclass

import structlog
from elasticsearch import AsyncElasticsearch

from pam.ingestion.embedders.base import BaseEmbedder

logger = structlog.get_logger()


@dataclass
class EntityVDBRecord:
    name: str
    entity_type: str
    description: str
    source_id: str
    file_path: str | None = None


@dataclass
class RelationshipVDBRecord:
    src_entity: str
    tgt_entity: str
    rel_type: str
    keywords: str
    description: str
    source_id: str
    weight: float = 1.0


class EntityRelationshipVDBStore:
    def __init__(
        self,
        client: AsyncElasticsearch,
        entity_index: str,
        relationship_index: str,
        embedding_dims: int,
    ) -> None:
        self.client = client
        self.entity_index = entity_index
        self.relationship_index = relationship_index
        self._embedding_dims = embedding_dims

    async def ensure_indices(self) -> None:
        """Create entity and relationship indices if they don't exist."""
        for index_name, mapping_fn in [
            (self.entity_index, get_entity_index_mapping),
            (self.relationship_index, get_relationship_index_mapping),
        ]:
            exists = await self.client.indices.exists(index=index_name)
            if not exists:
                await self.client.indices.create(
                    index=index_name, body=mapping_fn(self._embedding_dims)
                )
                logger.info("vdb_index_created", index=index_name)

    async def upsert_entities(
        self,
        entities: list[EntityVDBRecord],
        embedder: BaseEmbedder,
        source_id: str,
    ) -> int:
        """Embed and upsert entity records, skipping unchanged descriptions."""
        if not entities:
            return 0

        # Build embedding texts and hashes
        texts = [f"{e.name}\n{e.description}" for e in entities]
        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]

        # Check existing hashes to skip unchanged
        texts_to_embed, indices_to_embed = await self._filter_unchanged(
            self.entity_index,
            [e.name for e in entities],
            hashes,
        )

        # Embed only changed descriptions
        embeddings: dict[int, list[float]] = {}
        if texts_to_embed:
            raw_embeddings = await embedder.embed_texts(texts_to_embed)
            for idx, emb in zip(indices_to_embed, raw_embeddings):
                embeddings[idx] = emb

        # Bulk upsert
        actions = []
        upserted = 0
        for i, entity in enumerate(entities):
            if i not in embeddings:
                continue  # unchanged, skip
            actions.append({"index": {"_index": self.entity_index, "_id": entity.name}})
            actions.append({
                "name": entity.name,
                "entity_type": entity.entity_type,
                "description": entity.description,
                "embedding": embeddings[i],
                "content_hash": hashes[i],
                "source_ids": [source_id],
            })
            upserted += 1

        if actions:
            await self.client.bulk(operations=actions, refresh="wait_for")
            logger.info("entity_vdb_upsert", count=upserted, index=self.entity_index)

        return upserted
```

### kNN Search for Entity VDB
```python
async def search_entities(
    self,
    query_embedding: list[float],
    top_k: int = 5,
    entity_type: str | None = None,
) -> list[dict]:
    """Search entity VDB by vector similarity."""
    knn: dict = {
        "field": "embedding",
        "query_vector": query_embedding,
        "k": top_k,
        "num_candidates": top_k * 10,
    }
    if entity_type:
        knn["filter"] = {"term": {"entity_type": entity_type}}

    body = {
        "knn": knn,
        "size": top_k,
        "_source": {"excludes": ["embedding"]},
    }
    response = await self.client.search(index=self.entity_index, body=body)

    results = []
    for hit in response["hits"]["hits"]:
        src = hit["_source"]
        results.append({
            "name": src["name"],
            "entity_type": src.get("entity_type", ""),
            "description": src.get("description", ""),
            "score": hit.get("_score", 0.0),
            "source": "entity_vdb",
        })
    return results
```

### Extending smart_search for 4-Way Search
```python
# In agent.py _smart_search() -- extend existing gather
async def _entity_vdb_search_coro() -> list[dict]:
    if not hasattr(self, 'vdb_store') or self.vdb_store is None:
        return []
    embeddings = await self.embedder.embed_texts([es_query])
    return await self.vdb_store.search_entities(
        query_embedding=embeddings[0], top_k=5,
    )

async def _rel_vdb_search_coro() -> list[dict]:
    if not hasattr(self, 'vdb_store') or self.vdb_store is None:
        return []
    embeddings = await self.embedder.embed_texts([graph_query])
    return await self.vdb_store.search_relationships(
        query_embedding=embeddings[0], top_k=5,
    )

# 4-way gather
es_result, graph_result, entity_result, rel_result = await asyncio.gather(
    _es_search_coro(),
    _graph_search_coro(),
    _entity_vdb_search_coro(),
    _rel_vdb_search_coro(),
    return_exceptions=True,
)
```

### Relationship Document ID Construction
```python
def make_relationship_doc_id(src: str, rel_type: str, tgt: str) -> str:
    """Build deterministic ES document ID for a relationship.

    Sorts src/tgt alphabetically so A::REL::B == B::REL::A for undirected relationships.
    Includes rel_type to support multiple relationship types between the same entity pair.
    """
    sorted_pair = sorted([src, tgt])
    return f"{sorted_pair[0]}::{rel_type}::{sorted_pair[1]}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Search only document chunks (ES segments) | Also search entity and relationship descriptions | LightRAG (EMNLP 2025) | Enables semantic entity/relationship discovery without exact name matching |
| Single VDB (pam_segments) | 3-VDB pattern (segments + entities + relationships) | LightRAG 3-VDB architecture | Each VDB optimized for different query types: chunks for factual, entities for "who/what", relationships for "how/why" |
| Entity search only via Neo4j Cypher | kNN vector search on entity descriptions | This phase | Works without knowing exact entity names; semantic similarity matching |
| 2-way concurrent search (ES + Graphiti) | 4-way concurrent search (ES + Graphiti + entity VDB + rel VDB) | This phase | Richer results with distinct entity and relationship perspectives |

**Deprecated/outdated:**
- Single-index approach for all VDB data: LightRAG uses separate VDB stores for entities vs relationships because they have different field schemas and different query routing (low-level keywords -> entities, high-level keywords -> relationships).

## Open Questions

1. **source_ids Array Update Strategy**
   - What we know: Entities can be mentioned in multiple documents. The `source_ids` field should accumulate all contributing document source_ids.
   - What's unclear: ES `index` operation replaces the entire document, losing previous source_ids. We need either a scripted partial update or a read-modify-write pattern.
   - Recommendation: Use ES scripted upsert: `"script": {"source": "if (!ctx._source.source_ids.contains(params.new_id)) { ctx._source.source_ids.add(params.new_id) }"}` with `"upsert": {full_doc}`. This atomically adds the source_id if new, or creates the doc if it doesn't exist. Alternatively, for simplicity in Phase 13, overwrite with the current document's source_id and address multi-document entity aggregation in a later phase.

2. **Entity Name Collision Across Documents**
   - What we know: Different documents might refer to different things by the same name (e.g., "API" could mean different APIs in different contexts).
   - What's unclear: How Graphiti handles this -- does it merge or create separate entity nodes?
   - Recommendation: Graphiti merges entities by name within the same `group_id`. Since PAM uses `group_id=f"doc-{doc_id}"`, entities with the same name in different documents are in different groups. For the VDB, using entity name as ES doc ID means later ingestions overwrite earlier ones. This is acceptable because the VDB is for semantic discovery (find entities by description), not authoritative entity storage (that's Neo4j's role). Log when overwrites happen for visibility.

3. **Weight Calculation for Relationships**
   - What we know: The CONTEXT.md specifies a `weight` field in the relationship index. LightRAG uses weight to represent relationship strength.
   - What's unclear: Graphiti's `EntityEdge` doesn't have an explicit weight field.
   - Recommendation: Use `len(edge.episodes)` as a proxy for weight -- more episodes mentioning a relationship indicates stronger evidence. Default to 1.0 when only one episode references the edge.

4. **Embedding Query Reuse Between ES and VDB Searches**
   - What we know: In `_smart_search()`, the low-level keyword query is embedded for ES segment search. The same embedding could be reused for entity VDB search (both use the same query text).
   - What's unclear: Whether the query texts are identical enough to reuse embeddings.
   - Recommendation: Reuse the ES query embedding for entity VDB search (both use low-level keywords joined into a string). Similarly, create a single embedding for the high-level keyword query and reuse it for relationship VDB search. This halves the embedding API calls per search.

## Sources

### Primary (HIGH confidence)
- PAM codebase direct inspection: `extraction.py`, `elasticsearch_store.py`, `agent.py`, `config.py`, `pipeline.py`, `hybrid_search.py`, `openai_embedder.py`, `base.py` (embedder)
- Graphiti `AddEpisodeResults` class inspection: `nodes: list[EntityNode]` (with `name`, `summary`, `labels`, `uuid`), `edges: list[EntityEdge]` (with `name`, `fact`, `source_node_uuid`, `target_node_uuid`, `episodes`)
- Elasticsearch 8.19 `dense_vector` field type with cosine similarity -- same configuration as existing `pam_segments` index
- LightRAG GitHub (HKUDS/LightRAG) `operate.py` -- entity embedding format `"{name}\n{description}"`, relationship embedding format `"{keywords}\t{src}\n{tgt}\n{description}"`

### Secondary (MEDIUM confidence)
- LightRAG 3-VDB pattern: `entities_vdb`, `relationships_vdb`, `chunks_vdb` with `meta_fields` for source tracking
- ES kNN search API (`knn` query with `field`, `query_vector`, `k`, `num_candidates`, `filter`)

### Tertiary (LOW confidence)
- Orphan cleanup via `update_by_query` + `delete_by_query` -- standard ES pattern but not yet validated in this specific context

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and used; no new dependencies
- Architecture: HIGH -- patterns follow existing `ElasticsearchStore` and `extract_graph_for_document()` conventions; Graphiti return types verified by code inspection
- Pitfalls: HIGH -- identified from direct analysis of Graphiti `AddEpisodeResults` structure, entity UUID resolution across chunks, and `asyncio.gather` error handling patterns

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (stable -- no rapidly evolving dependencies)
