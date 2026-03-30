# Phase 15: Retrieval Mode Router - Research

**Researched:** 2026-02-27
**Domain:** Query intent classification + mode-based retrieval routing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Rule-based classifier as the primary layer -- keyword patterns, entity name detection, temporal markers
- Entity detection matches against known entities in the graph/ES (not just heuristic patterns)
- LLM fallback using Haiku (fastest, cheapest) for queries the rule-based layer can't confidently classify
- When neither rules nor LLM are confident, default to hybrid mode (search everything) -- never miss results
- All 5 modes implemented from the start: entity, conceptual, temporal, factual, hybrid
- **Entity mode**: shallow graph retrieval -- single node lookup + immediate neighbors (1-hop)
- **Conceptual mode**: deep graph retrieval -- multi-hop traversal, community structures, relationship patterns
- **Temporal mode**: triggered only by explicit time references -- keywords like 'when', 'history', 'changed', 'before/after', 'last week'
- **Factual mode**: ES-only, skip graph entirely -- triggered by direct definition/fact queries ("What is X?", "Define Y", "How many Z")
- **Hybrid mode**: all retrieval paths run -- the default fallback for ambiguous queries
- Agent receives the classified mode as a hint and passes it to smart_search (not transparent)
- Optional `mode` parameter in the search/chat API -- users can force a specific mode, skipping classification (for debugging and power users)
- Existing RRF scoring used as-is for multi-path merging -- mode routing controls WHICH paths run, not how results merge
- Mode + confidence score logged via structlog for every classification
- Mode included in API response metadata (`retrieval_mode`, `mode_confidence`) -- visible to frontend and API consumers
- Config-driven rules -- keyword lists, entity patterns, and confidence thresholds in config/env vars, tunable without code changes
- Per-mode performance metrics tracked: mode distribution, average latency per mode, fallback rates

### Claude's Discretion
- Hard skip vs soft skip strategy for skipped retrieval paths
- Exact confidence threshold values for hybrid fallback
- LLM classification prompt design
- Rule ordering and priority logic

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MODE-01 | `classify_query_mode()` function categorizes queries into 5 modes (entity, conceptual, temporal, factual, hybrid) with rule-based primary + LLM fallback | Architecture Pattern 1 (two-tier classifier), Pattern 2 (rule-based heuristics), Pattern 3 (LLM fallback). Builds on existing `extract_query_keywords()` in `keyword_extractor.py` for the LLM call pattern. |
| MODE-02 | `smart_search` uses classified mode to skip unnecessary retrieval paths, reducing latency for 40%+ of queries | Architecture Pattern 4 (mode-conditioned search execution). Modifies `_smart_search()` in `agent.py` to conditionally skip coroutines based on mode. Factual mode (ES-only) provides the largest latency win. |
| MODE-03 | Mode classification logged in agent response metadata for observability and tuning | Architecture Pattern 5 (observability integration). Extends `AgentResponse` and `ChatResponse` with `retrieval_mode` and `mode_confidence` fields. Structlog events for per-classification logging. |
</phase_requirements>

## Summary

Phase 15 adds a query classifier that routes each question to the optimal retrieval strategy before `smart_search` executes its 4-way concurrent search. The classifier categorizes queries into 5 modes (entity, conceptual, temporal, factual, hybrid) and each mode determines which of the 4 search paths (ES hybrid, Graphiti graph, entity VDB, relationship VDB) actually run. This is inspired by LightRAG's 6 retrieval modes (naive, local, global, hybrid, mix, bypass) but adapted to PAM's existing tool ecosystem and retrieval backends.

The implementation follows a two-tier classification approach: a fast rule-based classifier as the primary layer (regex patterns for temporal keywords, entity name matching against the `pam_entities` ES index, question-type heuristics for factual queries), with an LLM fallback via Claude Haiku (~30 tokens) for queries the rules cannot confidently classify. The classifier returns both a mode and a confidence score; when confidence is below the threshold, the system defaults to hybrid mode (all paths run) to avoid missing results. The mode is then used inside `_smart_search()` to conditionally skip unnecessary `asyncio.gather` coroutines -- for example, factual mode skips all three graph-related searches and only runs ES hybrid search.

All building blocks exist in the codebase. The keyword extraction LLM call pattern is established in `keyword_extractor.py`, concurrent search with `asyncio.gather` and `return_exceptions=True` is already in `_smart_search()`, structlog is used throughout, and the `AgentResponse`/`ChatResponse` models are easily extensible. The primary latency win comes from factual mode (ES-only, ~3-4x faster than hybrid) and entity mode (ES + entity VDB only, ~2x faster).

**Primary recommendation:** Implement the rule-based classifier as a pure function with configurable keyword lists (via Settings env vars), add an `async` entity name lookup against the `pam_entities` ES index for entity detection, and wire the LLM fallback using the existing `AsyncAnthropic` client with a minimal classification prompt. Skip strategy should be "hard skip" -- do not launch coroutines for skipped paths (replace with immediate empty results) rather than launching and ignoring.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic (AsyncAnthropic) | Already installed | LLM fallback classifier via Haiku | Project standard for all Claude API calls |
| elasticsearch (AsyncElasticsearch) | Already installed | Entity name lookup for rule-based classifier + ES search | Project standard search backend |
| asyncio | stdlib | Conditional concurrent search via asyncio.gather | Already used in `_smart_search()` |
| structlog | Already installed | Classification logging with mode + confidence | Project standard logging |
| re | stdlib | Temporal keyword and question pattern matching | Standard regex for rule-based classification |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | Already installed | Config settings for keyword lists, thresholds | For new `MODE_*` env vars in Settings |
| enum | stdlib | Mode enum definition | For type-safe mode representation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Rule-based + LLM fallback | LLM-only classification | Adds 500ms-2s latency to every query; rules handle 60-70% of queries in <1ms |
| Rule-based + LLM fallback | Rule-based only | Misses nuanced/ambiguous queries; LLM fallback covers the 30-40% gap |
| ES entity name lookup | In-memory entity cache | Cache needs invalidation on ingestion; ES lookup is <50ms and always fresh |
| Hard skip (don't launch) | Soft skip (launch, ignore results) | Hard skip saves actual compute and latency; soft skip is simpler but wasteful |

**Installation:**
No new packages needed. All dependencies are already in the project.

## Architecture Patterns

### Recommended Project Structure
```
src/pam/
├── agent/
│   ├── agent.py               # Modify _smart_search() to accept and use mode
│   ├── tools.py               # Add optional `mode` parameter to SMART_SEARCH_TOOL
│   ├── keyword_extractor.py   # No changes
│   ├── context_assembly.py    # No changes
│   └── query_classifier.py    # NEW: classify_query_mode() + RetrievalMode enum
├── common/
│   └── config.py              # Add MODE_* config settings (thresholds, keyword lists)
├── api/routes/
│   └── chat.py                # Add retrieval_mode + mode_confidence to ChatResponse
└── ...
```

### Pattern 1: Two-Tier Classification (Rule-Based + LLM Fallback)
**What:** A `classify_query_mode()` async function that first attempts rule-based classification, and falls back to an LLM call only when rule confidence is below a threshold.
**When to use:** Called at the start of `_smart_search()` before any retrieval.
**Key design points:**
- Return a `ClassificationResult(mode: RetrievalMode, confidence: float, method: str)` dataclass
- Rule-based layer runs synchronously (regex matching, keyword detection) -- <1ms
- Entity name lookup is async (ES query against `pam_entities` index) -- <50ms
- LLM fallback only fires when rule confidence < threshold (default 0.7)
- Hybrid is the safety-net default when nothing else matches or LLM confidence is low

```python
# src/pam/agent/query_classifier.py
from enum import Enum
from dataclasses import dataclass

class RetrievalMode(str, Enum):
    ENTITY = "entity"
    CONCEPTUAL = "conceptual"
    TEMPORAL = "temporal"
    FACTUAL = "factual"
    HYBRID = "hybrid"

@dataclass
class ClassificationResult:
    mode: RetrievalMode
    confidence: float  # 0.0 - 1.0
    method: str        # "rules" or "llm"

async def classify_query_mode(
    query: str,
    client: AsyncAnthropic | None = None,
    vdb_store: EntityRelationshipVDBStore | None = None,
    confidence_threshold: float = 0.7,
) -> ClassificationResult:
    # Step 1: Rule-based classification
    result = _rule_based_classify(query)
    if result.confidence >= confidence_threshold:
        return result

    # Step 2: Entity name lookup (async)
    if vdb_store is not None:
        entity_result = await _check_entity_mentions(query, vdb_store)
        if entity_result is not None and entity_result.confidence >= confidence_threshold:
            return entity_result

    # Step 3: LLM fallback
    if client is not None:
        llm_result = await _llm_classify(query, client)
        if llm_result.confidence >= confidence_threshold:
            return llm_result

    # Step 4: Default to hybrid
    return ClassificationResult(
        mode=RetrievalMode.HYBRID,
        confidence=0.5,
        method="default",
    )
```

### Pattern 2: Rule-Based Heuristics
**What:** A synchronous function that classifies queries using regex patterns and keyword matching.
**When to use:** First step in the two-tier classifier.
**Key design points:**
- Temporal detection: regex for time-related keywords (`when`, `history`, `changed`, `before`, `after`, `since`, `last week`, `last month`, ISO date patterns)
- Factual detection: question patterns (`what is`, `define`, `how many`, `who is`, `list the`, `describe`)
- Conceptual detection: relationship/pattern keywords (`depends on`, `related to`, `connects`, `impact`, `affects`, `why does`)
- Entity detection: presence of capitalized multi-word proper nouns (heuristic fallback; the real entity check is async)
- Each rule returns a confidence score; highest-confidence rule wins
- Keyword lists stored in config (env vars) for tunability

```python
import re

# Configurable keyword lists (loaded from Settings)
TEMPORAL_KEYWORDS = [
    r'\bwhen\b', r'\bhistory\b', r'\bchanged\b', r'\bbefore\b', r'\bafter\b',
    r'\bsince\b', r'\blast\s+(?:week|month|year|quarter)\b', r'\brecently\b',
    r'\btimeline\b', r'\bevolution\b', r'\bover\s+time\b',
    r'\d{4}-\d{2}',  # ISO date fragments
]
FACTUAL_PATTERNS = [
    r'^what\s+is\b', r'^define\b', r'^how\s+many\b', r'^who\s+is\b',
    r'^list\s+the\b', r'^describe\b', r'^what\s+does\b', r'^what\s+are\b',
]
CONCEPTUAL_KEYWORDS = [
    r'\bdepends?\s+on\b', r'\brelated\s+to\b', r'\bconnect', r'\bimpact\b',
    r'\baffects?\b', r'\bwhy\s+does\b', r'\brelationship\b', r'\barchitecture\b',
    r'\bpattern\b', r'\binteraction\b',
]

def _rule_based_classify(query: str) -> ClassificationResult:
    query_lower = query.lower().strip()

    # Temporal (highest specificity)
    temporal_matches = sum(1 for p in TEMPORAL_KEYWORDS if re.search(p, query_lower))
    if temporal_matches >= 2:
        return ClassificationResult(RetrievalMode.TEMPORAL, 0.9, "rules")
    if temporal_matches == 1:
        return ClassificationResult(RetrievalMode.TEMPORAL, 0.75, "rules")

    # Factual (question-pattern matching)
    for pattern in FACTUAL_PATTERNS:
        if re.match(pattern, query_lower):
            return ClassificationResult(RetrievalMode.FACTUAL, 0.8, "rules")

    # Conceptual (relationship keywords)
    conceptual_matches = sum(1 for p in CONCEPTUAL_KEYWORDS if re.search(p, query_lower))
    if conceptual_matches >= 2:
        return ClassificationResult(RetrievalMode.CONCEPTUAL, 0.85, "rules")
    if conceptual_matches == 1:
        return ClassificationResult(RetrievalMode.CONCEPTUAL, 0.7, "rules")

    # No confident match
    return ClassificationResult(RetrievalMode.HYBRID, 0.4, "rules")
```

### Pattern 3: Entity Name Detection via ES Lookup
**What:** An async function that checks if the query mentions known entity names from the `pam_entities` ES index.
**When to use:** When rule-based classification returns low confidence and entity-specific retrieval might be optimal.
**Key design points:**
- Use ES `terms` query on the `name` keyword field (exact match) or `match` query for fuzzy matching
- Extract candidate entity names from the query using simple tokenization (capitalized words, multi-word phrases)
- If any known entity is found, classify as `entity` mode with high confidence
- Cache entity name list for short periods (optional optimization) or query live each time (<50ms)

```python
async def _check_entity_mentions(
    query: str,
    vdb_store: EntityRelationshipVDBStore,
) -> ClassificationResult | None:
    """Check if query mentions known entities in the pam_entities index."""
    # Extract candidate names: capitalized words and multi-word phrases
    candidates = _extract_candidate_names(query)
    if not candidates:
        return None

    # Query ES for matching entity names
    body = {
        "query": {
            "terms": {"name": [c.lower() for c in candidates]}
        },
        "size": 1,
        "_source": ["name"],
    }
    try:
        response = await vdb_store.client.search(
            index=vdb_store.entity_index,
            body=body,
        )
        if response["hits"]["total"]["value"] > 0:
            return ClassificationResult(RetrievalMode.ENTITY, 0.85, "rules")
    except Exception:
        pass  # Graceful degradation; entity check is best-effort
    return None
```

### Pattern 4: Mode-Conditioned Search Execution
**What:** Modify `_smart_search()` to accept a `RetrievalMode` and conditionally skip retrieval paths.
**When to use:** Inside `_smart_search()` after classification, before `asyncio.gather`.
**Key design points:**
- Hard skip: replace skipped coroutines with immediate empty results (no launch)
- Mode-to-paths mapping:
  - `factual` -> ES only (skip graph, entity VDB, relationship VDB)
  - `entity` -> ES + entity VDB (skip graph, relationship VDB)
  - `conceptual` -> Graph + relationship VDB (skip ES, entity VDB) -- or include ES at reduced limit
  - `temporal` -> All paths (temporal queries need broad context) -- same as hybrid but with temporal keywords in query
  - `hybrid` -> All 4 paths (default, no skipping)
- The existing `asyncio.gather` pattern handles this naturally: build a list of coroutines dynamically based on mode

```python
# Inside _smart_search(), after classification:

async def _noop_list() -> list:
    return []

async def _noop_str() -> str:
    return ""

# Build coroutine list based on mode
if mode == RetrievalMode.FACTUAL:
    coros = [_es_search_coro(), _noop_str(), _noop_list(), _noop_list()]
elif mode == RetrievalMode.ENTITY:
    coros = [_es_search_coro(), _noop_str(), _entity_vdb_search_coro(), _noop_list()]
elif mode == RetrievalMode.CONCEPTUAL:
    coros = [_noop_list(), _graph_search_coro(), _noop_list(), _rel_vdb_search_coro()]
elif mode == RetrievalMode.TEMPORAL:
    coros = [_es_search_coro(), _graph_search_coro(), _entity_vdb_search_coro(), _rel_vdb_search_coro()]
else:  # HYBRID
    coros = [_es_search_coro(), _graph_search_coro(), _entity_vdb_search_coro(), _rel_vdb_search_coro()]

es_result, graph_result, entity_vdb_result, rel_vdb_result = await asyncio.gather(
    *coros, return_exceptions=True,
)
```

### Pattern 5: Observability Integration
**What:** Log classification results via structlog and expose mode in API response metadata.
**When to use:** After classification (for logging) and after agent response (for API metadata).
**Key design points:**
- `structlog.info("query_mode_classified", mode=result.mode.value, confidence=result.confidence, method=result.method)`
- Extend `AgentResponse` with optional `retrieval_mode: str | None` and `mode_confidence: float | None` fields
- Extend `ChatResponse` Pydantic model with same fields
- Streaming SSE `done` event includes mode metadata alongside existing token_usage/latency_ms
- Per-mode latency tracking via existing `CostTracker` or simple structlog events

### Anti-Patterns to Avoid
- **LLM-first classification:** Never call the LLM for every query. The rule-based layer handles 60-70% of queries in <1ms. LLM adds 500ms-2s per call.
- **Soft skip (launch and discard):** Do not launch all 4 search coroutines and discard results post-hoc. This wastes compute and does not reduce latency. Use hard skip with noop coroutines.
- **Hardcoded keyword lists:** Keywords, thresholds, and patterns must be in config/env vars per the user decision. Do not hardcode them in the classifier function body.
- **Transparent mode passing:** The user decided the agent receives the mode as a hint (not transparent). Do not silently apply mode routing without the agent/API consumer knowing which mode was used.
- **Over-aggressive factual classification:** Be conservative with factual mode since it skips the graph entirely. A query like "What is AuthService?" could be factual (definition) or entity (graph lookup). When in doubt, prefer hybrid over factual.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ES hybrid search | Custom ES query builder | `HybridSearchService.search()` | Already handles RRF, kNN + BM25 fusion |
| Graph relationship search | Custom Cypher queries | `search_graph_relationships()` from `graph/query.py` | Handles Graphiti search, episode extraction, truncation |
| Entity VDB search | Custom kNN query builder | `EntityRelationshipVDBStore.search_entities()` | Already implements kNN with optional type filtering |
| LLM classification call | Custom HTTP client | `AsyncAnthropic.messages.create()` with Haiku | Existing pattern from `keyword_extractor.py` |
| Token counting | Character-based estimation | `tiktoken` via `context_assembly.count_tokens()` | Already implemented and cached in the project |
| Config management | Custom config parsing | Pydantic Settings in `config.py` | Project standard for all env-var-driven config |

**Key insight:** The mode router is pure orchestration logic. Every retrieval backend, LLM call pattern, logging pattern, and config pattern already exists. The new code is: (1) a classifier module with regex + ES lookup + LLM fallback, (2) conditional coroutine selection in `_smart_search()`, and (3) metadata propagation to the API response.

## Common Pitfalls

### Pitfall 1: Classification Latency Negating Skip Savings
**What goes wrong:** If the classifier itself is slow (entity ES lookup + LLM fallback), the time saved by skipping retrieval paths is eaten by classification overhead.
**Why it happens:** The rule-based layer is <1ms, but entity ES lookup adds ~50ms and LLM fallback adds 500ms-2s. If 40% of queries hit the LLM fallback, average savings may be negative.
**How to avoid:** Structure the classifier as a cascade: rules first (free), entity lookup only if rules are uncertain, LLM only as last resort. Target <5% of queries hitting the LLM fallback by making rules comprehensive. Consider making the entity ES lookup optional (only when rules suggest an entity-like query).
**Warning signs:** Average smart_search latency increases after adding the mode router.

### Pitfall 2: Factual Mode Missing Graph-Relevant Answers
**What goes wrong:** A query like "What teams use Kubernetes?" is classified as factual ("What..." pattern) but the best answer is in the knowledge graph (team-technology relationships).
**Why it happens:** Factual pattern matching is too aggressive -- "What..." is a common prefix for many query types.
**How to avoid:** Add negative signals to factual classification: if the query also contains entity names or relationship keywords, do NOT classify as factual. Use confidence scoring rather than binary matching -- "What is X?" (high factual confidence) vs "What teams use X?" (low factual confidence, triggers hybrid fallback).
**Warning signs:** Eval scores on relationship questions drop after enabling mode routing.

### Pitfall 3: Entity Name Lookup Returning Stale Results
**What goes wrong:** The `pam_entities` ES index is queried for entity names, but after a fresh ingestion the index may not be up to date (eventual consistency).
**Why it happens:** ES index refresh is not instant; VDB upsert uses `refresh="wait_for"` but there can be a gap.
**How to avoid:** Entity name lookup is best-effort -- if it fails or returns no results, the classifier falls through to the next tier (LLM or hybrid default). Do not make classification correctness dependent on entity lookup always succeeding.
**Warning signs:** Queries about recently ingested entities get classified as factual instead of entity mode.

### Pitfall 4: Confidence Threshold Too Low or Too High
**What goes wrong:** If the threshold is too low (e.g., 0.5), queries are aggressively routed to specific modes and miss results. If too high (e.g., 0.95), everything falls through to hybrid and the router has no effect.
**Why it happens:** The threshold is a tuning parameter with no perfect default.
**How to avoid:** Start with a conservative threshold (0.7) that errs toward hybrid fallback. Log mode distribution and track per-mode result quality via eval. Adjust the threshold based on data. Make it configurable via env var.
**Warning signs:** Either all queries route to hybrid (threshold too high) or eval scores drop on specific query types (threshold too low).

### Pitfall 5: Mode Enum Inconsistency Between Classifier and Router
**What goes wrong:** The classifier returns a mode string, the router expects an enum, or vice versa. Or the API exposes a different set of modes than the classifier produces.
**Why it happens:** Mode is defined in multiple places (classifier, router, API model) without a single source of truth.
**How to avoid:** Define `RetrievalMode` as a `str, Enum` in the classifier module and import it everywhere. Use `mode.value` for serialization. Never use raw strings for mode comparison.
**Warning signs:** KeyError or AttributeError when the mode reaches the router or API response.

## Code Examples

### RetrievalMode Enum
```python
# src/pam/agent/query_classifier.py
from enum import Enum

class RetrievalMode(str, Enum):
    """Retrieval strategy modes for query routing."""
    ENTITY = "entity"           # Shallow graph: ES + entity VDB
    CONCEPTUAL = "conceptual"   # Deep graph: Graphiti + relationship VDB
    TEMPORAL = "temporal"       # All paths with temporal focus
    FACTUAL = "factual"         # ES-only, skip graph entirely
    HYBRID = "hybrid"           # All 4 retrieval paths (default)
```

### Smart Search Tool with Optional Mode Parameter
```python
# Updated SMART_SEARCH_TOOL in tools.py
SMART_SEARCH_TOOL: dict[str, Any] = {
    "name": "smart_search",
    "description": (
        "Search both documents and the knowledge graph in one call. "
        "Extracts key concepts and entities from your query, then searches "
        "documents (text/semantic) and the knowledge graph (relationships) concurrently. "
        "Returns document results and graph results in separate sections."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query to search across documents and the knowledge graph.",
            },
            "mode": {
                "type": "string",
                "enum": ["entity", "conceptual", "temporal", "factual", "hybrid"],
                "description": (
                    "Optional: force a specific retrieval mode, skipping auto-classification. "
                    "Modes: entity (graph-first), conceptual (relationship-first), "
                    "temporal (history-first), factual (ES-only), hybrid (all sources)."
                ),
            },
        },
        "required": ["query"],
    },
}
```

### Extended AgentResponse with Mode Metadata
```python
# Updated AgentResponse in agent.py
@dataclass
class AgentResponse:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    tool_calls: int = 0
    retrieval_mode: str | None = None
    mode_confidence: float | None = None
```

### Extended ChatResponse with Mode Metadata
```python
# Updated ChatResponse in chat.py
class ChatResponse(BaseModel):
    response: str
    citations: list[dict]
    conversation_id: str | None
    token_usage: dict
    latency_ms: float
    retrieval_mode: str | None = None
    mode_confidence: float | None = None
```

### Config Settings for Mode Router
```python
# Additions to Settings in config.py
# Mode Router
mode_confidence_threshold: float = 0.7  # Below this, fall back to hybrid
mode_temporal_keywords: str = "when,history,changed,before,after,since,recently,timeline,evolution"
mode_factual_patterns: str = "what is,define,how many,who is,list the,describe,what does,what are"
mode_conceptual_keywords: str = "depends on,related to,connect,impact,affects,why does,relationship,architecture,pattern"
mode_llm_fallback_enabled: bool = True  # Set False to use rules-only
```

### Classification Logging
```python
# Inside _smart_search, after classification:
logger.info(
    "query_mode_classified",
    mode=result.mode.value,
    confidence=result.confidence,
    method=result.method,
    query=query[:100],
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Same query to all backends | Mode-based routing skips irrelevant paths | LightRAG (EMNLP 2025) | 40-60% latency reduction for factual/entity queries |
| LLM-only query classification | Rule-based primary + LLM fallback | Industry consensus 2025 | Rules handle 60-70% at <1ms; LLM is safety net for the rest |
| Fixed retrieval pipeline | Adaptive per-query retrieval | RAG routing research 2025 | 18% retrieval relevance improvement in production systems |
| Opaque retrieval decisions | Mode logging + API metadata exposure | Observability best practice | Enables data-driven tuning of classification rules |

**Deprecated/outdated:**
- LLM-only classification for every query: adds 500ms-2s overhead to every request; rule-based handles the majority. Industry consensus in 2025 is that keyword/regex rules are "fast and surprisingly effective" with ML/LLM adding only 2% accuracy improvement.
- Transparent mode routing (hidden from API consumers): modern systems expose routing decisions for debugging and tuning.

## Open Questions

1. **Entity name lookup: ES terms query vs ES search query**
   - What we know: The `pam_entities` index has a `name` field typed as `keyword` (exact match). Entity names are stored as-is (e.g., "AuthService", "SalesTeam").
   - What's unclear: Whether to use an exact `terms` query (fast, requires exact match) or a `match` query (slower, handles partial matches). The user decision says "matches against known entities" -- unclear if this means fuzzy or exact.
   - Recommendation: Use ES `terms` query for exact matching first. If no match, try a `match_phrase_prefix` query as a fallback. This gives speed for exact hits and flexibility for partial mentions.

2. **Conceptual mode: should it include ES results?**
   - What we know: Conceptual mode is defined as "deep graph retrieval -- multi-hop traversal, community structures, relationship patterns." The user decision says it's relationship-first.
   - What's unclear: Whether conceptual mode should also include ES document chunks (at reduced limit) or skip ES entirely. Pure graph-only may miss relevant document context.
   - Recommendation: Include ES at a reduced limit (e.g., 2 results instead of 5) for conceptual mode. Completely skipping document chunks risks losing context that supports graph findings.

3. **Temporal mode: same as hybrid or distinct?**
   - What we know: Temporal mode should include all retrieval paths since temporal queries often need broad context. The user defined it as triggered by time references.
   - What's unclear: Whether temporal mode behaves identically to hybrid (making it redundant) or should adjust query formulation (e.g., adding time context to graph queries).
   - Recommendation: Temporal mode runs all paths like hybrid, but adds a structlog tag and passes temporal keywords to the graph query for better edge temporal filtering. This makes it observably distinct from hybrid without reducing retrieval coverage.

4. **Mode parameter on the API: chat endpoint only or also search endpoint?**
   - What we know: The user decision says "optional mode parameter in the search/chat API." The current `/api/search` endpoint is a direct ES search without the agent.
   - What's unclear: Whether mode routing applies to the direct `/api/search` endpoint or only to `/api/chat` and `/api/chat/stream`.
   - Recommendation: Add the mode parameter to the chat endpoints only. The direct search endpoint bypasses the agent and has no concept of retrieval modes.

## Sources

### Primary (HIGH confidence)
- PAM codebase direct inspection -- `agent.py` (smart_search implementation, AgentResponse), `tools.py` (tool definitions), `keyword_extractor.py` (LLM call pattern), `context_assembly.py` (token budgets), `config.py` (Settings pattern), `deps.py` (DI pattern), `chat.py` (ChatResponse model), `entity_relationship_store.py` (entity VDB search methods), `entity_types.py` (entity taxonomy), `query.py` (graph query functions)
- LightRAG GitHub repository (HKUDS/LightRAG) -- 6 retrieval modes (naive, local, global, hybrid, mix, bypass), mode-to-VDB routing, QueryParam configuration
- [DeepWiki: LightRAG Query Engine](https://deepwiki.com/HKUDS/LightRAG/2.3-query-engine) -- detailed mode comparison table, per-mode storage backend routing, token budget system

### Secondary (MEDIUM confidence)
- [Query Routing for Retrieval-Augmented Language Models (arXiv 2505.23052)](https://arxiv.org/html/2505.23052v1) -- query routing strategies for RAG systems
- [LLM-Based Prompt Routing (EmergentMind)](https://www.emergentmind.com/topics/llm-based-prompt-routing) -- rule-based vs LLM-based routing tradeoffs
- [Doing More with Less: Routing Strategies in LLM Systems (arXiv 2502.00409)](https://arxiv.org/html/2502.00409v1) -- routing mechanism taxonomy

### Tertiary (LOW confidence)
- Medium articles on RAG query classification -- anecdotal production numbers (18% relevance improvement, 2% accuracy delta between rules and ML)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already installed; no new dependencies
- Architecture: HIGH - patterns follow existing codebase conventions; all building blocks verified in source code; two-tier classification is well-documented industry pattern
- Pitfalls: HIGH - identified from direct code analysis of existing smart_search, async patterns, and LightRAG mode routing behavior

**Research date:** 2026-02-27
**Valid until:** 2026-03-27 (stable -- no rapidly evolving dependencies)
