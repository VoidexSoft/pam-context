# Phase 12: Dual-Level Keyword Extraction + Unified Search Tool - Research

**Researched:** 2026-02-24
**Domain:** LLM-driven query keyword extraction + concurrent multi-backend search merging
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Always extract both high-level and low-level keywords regardless of query ambiguity -- ensures both ES and graph backends always contribute
- Return two separate sections: `document_results` and `graph_results` arrays (not a single merged list)
- Graph results must include relationship structure: source entity, target entity, relationship type, plus text content
- Response must include the extracted `high_level_keywords` and `low_level_keywords` alongside results -- transparency for the agent and useful for debugging/eval
- Default 10 total results: 5 from ES, 5 from graph
- Limits configurable via env vars (SMART_SEARCH_ES_LIMIT, SMART_SEARCH_GRAPH_LIMIT)
- Backfill enabled: if one source returns fewer than its quota, the other source fills the gap up to total limit
- Deduplication by content hash favors the ES version (carries document citations and chunk context needed for the agent's citation workflow)
- If keyword extraction LLM call fails: return error to agent (agent can retry or fall back to individual search tools)
- If one search backend fails (e.g. Neo4j down): return partial results from the working backend, with a warning field indicating which backend failed
- Agent routing: describe all three tools (smart_search, search_knowledge, search_knowledge_graph) equally -- let the agent decide per-query which to use, no forced preference in system prompt
- Keyword extraction timeout: generous 10-15 seconds (allows for cold starts / API congestion)

### Claude's Discretion
- Keyword extraction prompt wording and few-shot examples
- Whether to pass the original query as an implicit low-level keyword to ES
- Exact keyword count caps (fixed vs variable)
- Loading/progress behavior for concurrent searches
- Error message formatting
- Whether individual results carry a source tag

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SMART-01 | `smart_search` tool that accepts natural language query and returns merged ES + graph results | Architecture Pattern 1 (tool definition), Pattern 2 (concurrent search), Pattern 3 (result merging). Builds on existing `_search_knowledge` and `_search_knowledge_graph` patterns in `agent.py`. |
| SMART-02 | Keyword extraction via Claude call producing `{high_level_keywords, low_level_keywords}` (~50 tokens) | Architecture Pattern 1 (extraction function). LightRAG prompt template adapted for PAM. Follows existing `EntityExtractor` pattern for LLM calls. |
| SMART-03 | Low-level keywords drive ES hybrid search, high-level keywords drive Graphiti edge search, both concurrent | Architecture Pattern 2 (concurrent execution via `asyncio.gather`). ES uses existing `HybridSearchService.search()`, graph uses existing `search_graph_relationships()` from `query.py`. |
</phase_requirements>

## Summary

Phase 12 introduces a `smart_search` agent tool that unifies document search (ES) and knowledge graph search (Graphiti) into a single tool call, inspired by LightRAG's dual-level retrieval pattern. The core pattern is: (1) extract high-level (theme) and low-level (entity) keywords from the user query via a lightweight Claude call, (2) run ES hybrid search with low-level keywords and Graphiti semantic edge search with high-level keywords in parallel, (3) merge results with deduplication by content hash, and (4) return structured results in two sections alongside the extracted keywords.

The implementation is straightforward because all building blocks exist. The ES hybrid search is available via `HybridSearchService.search()`, the graph search via `search_graph_relationships()` in `graph/query.py`, the Anthropic SDK async client is already used throughout the codebase, and `asyncio.gather` provides concurrency. The new code creates: (a) an `extract_query_keywords()` function following the existing `EntityExtractor` pattern for LLM calls, (b) a `smart_search` tool definition in `tools.py`, (c) a `_smart_search()` handler in `agent.py`, and (d) env-var-driven configuration in `config.py`.

**Primary recommendation:** Follow the existing `EntityExtractor` pattern (lightweight Anthropic SDK call with JSON output parsing) for keyword extraction, and use `asyncio.gather` to run ES + Graphiti searches in parallel. Keep the extraction prompt minimal (~50 output tokens) with 3 few-shot examples adapted from LightRAG.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic (AsyncAnthropic) | Already installed | Keyword extraction LLM call | Project standard for all Claude API interactions |
| elasticsearch (AsyncElasticsearch) | Already installed | ES hybrid search via HybridSearchService | Project standard search backend |
| graphiti-core | 0.28.1 (installed) | Graph edge search via Graphiti.search() | Project standard graph backend |
| asyncio | stdlib | Concurrent search via asyncio.gather | Python standard for parallel async operations |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | Already installed | Result schema validation, config env vars | For SmartSearchResult model and SMART_SEARCH_* settings |
| structlog | Already installed | Structured logging of keyword extraction + search timing | All logging in this phase |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Anthropic SDK for keyword extraction | Regex/rule-based extraction | User decision: use LLM. Rules would miss nuance but avoid latency/cost |
| asyncio.gather for concurrency | Sequential calls | gather is ~2x faster for 2 independent async calls; no downside |

**Installation:**
No new packages needed. All dependencies are already in the project.

## Architecture Patterns

### Recommended Project Structure
```
src/pam/
├── agent/
│   ├── agent.py              # Add _smart_search() handler + _execute_tool dispatch
│   ├── tools.py              # Add SMART_SEARCH_TOOL definition
│   └── keyword_extractor.py  # NEW: extract_query_keywords() function
├── common/
│   └── config.py             # Add SMART_SEARCH_ES_LIMIT, SMART_SEARCH_GRAPH_LIMIT env vars
├── retrieval/
│   └── hybrid_search.py      # No changes (used as-is)
└── graph/
    └── query.py              # No changes (used as-is)
```

### Pattern 1: Keyword Extraction Function
**What:** A standalone async function that calls Claude with a minimal prompt to extract high-level and low-level keywords from a query, returning structured JSON.
**When to use:** Called by `_smart_search()` before retrieval.
**Key design points:**
- Follow `EntityExtractor` pattern: `AsyncAnthropic` client, `messages.create()`, JSON parsing
- Use `max_tokens=100` to keep extraction lightweight (~50 output tokens)
- Use Claude Haiku (claude-3-5-haiku-20241022) for speed and cost -- keyword extraction is a classification task, not generation
- Return a Pydantic model `QueryKeywords(high_level_keywords: list[str], low_level_keywords: list[str])`
- Catch `json.JSONDecodeError` and return empty lists on failure (agent gets error, can retry)
- Configurable timeout via `httpx` timeout parameter on the Anthropic client

**Prompt template (adapted from LightRAG):**
```
You are a keyword extractor for a RAG system. Given a user query, extract:
- high_level_keywords: overarching themes, concepts, or relationship types (e.g., "dependencies", "team ownership", "deployment process")
- low_level_keywords: specific entities, proper nouns, technical terms (e.g., "AuthService", "Q3 revenue", "Kubernetes")

Output a JSON object with exactly two keys: "high_level_keywords" and "low_level_keywords", each an array of strings. Output JSON only.

Examples:
Query: "What services depend on the authentication module?"
{"high_level_keywords": ["service dependencies", "system architecture"], "low_level_keywords": ["authentication module"]}

Query: "How has the deployment process changed since January?"
{"high_level_keywords": ["process evolution", "deployment changes"], "low_level_keywords": ["deployment process", "January"]}

Query: "What is the conversion rate formula?"
{"high_level_keywords": ["metric definition", "business analytics"], "low_level_keywords": ["conversion rate", "formula"]}

Query: "{query}"
```

### Pattern 2: Concurrent Search Execution
**What:** Run ES hybrid search and Graphiti graph search in parallel using `asyncio.gather`.
**When to use:** Inside `_smart_search()` after keyword extraction.
**Key design points:**
- ES search: join low-level keywords into a single query string, embed via `self.embedder.embed_texts()`, call `self.search.search()`
- Graph search: join high-level keywords into a single query string, call `search_graph_relationships()` from `graph/query.py`
- Use `asyncio.gather(es_task, graph_task, return_exceptions=True)` so one failure does not block the other
- Check each result: if it is an Exception, set that source's results to empty list and populate the `warning` field
- Total latency = max(ES latency, graph latency) + keyword extraction latency (sequential prerequisite)

**Example:**
```python
import asyncio

async def _smart_search(self, input_: dict) -> tuple[str, list[Citation]]:
    query = input_["query"]

    # Step 1: Extract keywords (sequential -- needed before search)
    keywords = await extract_query_keywords(self.client, self.model, query)

    # Step 2: Prepare search queries
    es_query = " ".join(keywords.low_level_keywords) if keywords.low_level_keywords else query
    graph_query = " ".join(keywords.high_level_keywords) if keywords.high_level_keywords else query

    # Step 3: Run both searches concurrently
    es_coro = self._es_search(es_query, es_limit)
    graph_coro = self._graph_search(graph_query, graph_limit)
    es_result, graph_result = await asyncio.gather(es_coro, graph_coro, return_exceptions=True)

    # Step 4: Handle partial failures
    # Step 5: Deduplicate and merge
    # Step 6: Format and return
```

### Pattern 3: Result Merging with Backfill and Dedup
**What:** Merge ES and graph results: round-robin interleave for internal ordering, then split into two sections, with backfill when one source returns fewer results.
**When to use:** Inside `_smart_search()` after both searches complete.
**Key design points:**
- Dedup by content hash: if same content appears in both ES and graph results, keep the ES version (per user decision -- ES carries citations)
- Backfill logic: if ES returns 3 of 5 requested, graph can return up to 7 (total capped at 10)
- The final output has `document_results` and `graph_results` as separate arrays (per user decision)
- Content hash for dedup: compute SHA-256 of result text content (same approach used in ingestion pipeline)

### Anti-Patterns to Avoid
- **Chained sequential searches:** Never run ES search then graph search sequentially when they are independent -- always use asyncio.gather
- **Keyword extraction in the agent loop:** The extraction must happen inside the tool, not as a separate agent reasoning step. The goal is 1 tool call, not 2+
- **Hardcoded result limits:** Use env vars as decided -- SMART_SEARCH_ES_LIMIT and SMART_SEARCH_GRAPH_LIMIT
- **Swallowing extraction errors silently:** If keyword extraction fails, return an error to the agent (per user decision) rather than falling back to a default query. The agent can retry or use individual tools
- **Mixing result sections:** User decided on separate `document_results` and `graph_results` arrays -- do not merge into a single list

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ES hybrid search | Custom ES query builder | `HybridSearchService.search()` | Already handles RRF, filters, reranking |
| Graph edge search | Custom Cypher queries | `search_graph_relationships()` from `graph/query.py` | Already handles Graphiti search, episode source extraction, truncation |
| Async concurrency | Threading or multiprocessing | `asyncio.gather()` | All existing code is async; mixing paradigms causes bugs |
| JSON parsing with retries | Custom retry/parse logic | Standard `json.loads()` with try/except | Extraction is lightweight; failures are rare and handled by error return |
| Content hashing | Custom hash function | `hashlib.sha256(content.encode()).hexdigest()` | Same pattern used throughout ingestion pipeline (`content_hash` field) |

**Key insight:** Every component needed for this phase already exists. The new code is purely orchestration -- connecting keyword extraction to existing search backends and formatting the combined output.

## Common Pitfalls

### Pitfall 1: Keyword Extraction Latency Dominating Total Latency
**What goes wrong:** The Claude API call for keyword extraction adds 500ms-2s before any search begins, making `smart_search` slower than calling `search_knowledge` directly.
**Why it happens:** LLM calls have inherent latency; keyword extraction is a sequential prerequisite.
**How to avoid:** Use Claude Haiku (not Sonnet) for extraction -- it is 5-10x faster and sufficient for a classification task. Set `max_tokens=100` to avoid long completions. Consider passing the original query as an additional implicit low-level keyword to ES so results are relevant even if extraction produces suboptimal keywords.
**Warning signs:** P95 latency for `smart_search` exceeds 3s when individual tools complete in <1s.

### Pitfall 2: Empty Keywords Causing Empty Results
**What goes wrong:** If the LLM returns empty keyword arrays (e.g., for very short queries like "hello"), both searches get empty queries and return nothing.
**Why it happens:** The LightRAG prompt instructs to return empty arrays for nonsensical queries.
**How to avoid:** Fall back to the original query when either keyword array is empty. Always pass the original query to at least the ES search path.
**Warning signs:** `smart_search` returns 0 results for queries that `search_knowledge` handles fine.

### Pitfall 3: Asyncio.gather Exception Propagation
**What goes wrong:** If `return_exceptions=False` (default) is used, one search backend failing kills the entire gather, losing results from the working backend.
**Why it happens:** Default asyncio.gather behavior cancels siblings on first exception.
**How to avoid:** Always use `return_exceptions=True` and check each result with `isinstance(result, Exception)`.
**Warning signs:** Neo4j going down causes `smart_search` to return 0 results instead of partial ES results.

### Pitfall 4: Dedup False Negatives on Similar-But-Different Content
**What goes wrong:** ES result and graph result describe the same fact with different text, so content hash dedup misses the duplicate.
**Why it happens:** Content hash is exact-match only; semantic dedup requires embedding similarity.
**How to avoid:** Accept this limitation for Phase 12 -- exact content hash dedup catches the most common case (same chunk appearing in both backends). Semantic dedup is a Phase 14+ concern.
**Warning signs:** Users see near-identical results in both `document_results` and `graph_results` sections.

### Pitfall 5: System Prompt Tool Count Explosion
**What goes wrong:** Adding a new tool definition increases the system prompt size, potentially degrading tool selection accuracy or increasing input token costs.
**Why it happens:** Claude must parse all tool definitions on every call. Currently 7 tools; adding 1 more brings it to 8.
**How to avoid:** Keep the `smart_search` tool description concise. The user decided to describe all three search tools equally -- do NOT add long explanatory text comparing them. One clear sentence per tool is sufficient.
**Warning signs:** Agent starts using wrong tools or ignoring available tools after adding `smart_search`.

## Code Examples

### Keyword Extraction Function
```python
# src/pam/agent/keyword_extractor.py
import json
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

logger = structlog.get_logger()

KEYWORD_EXTRACTION_PROMPT = """You are a keyword extractor for a RAG system. Given a user query, extract:
- high_level_keywords: overarching themes, concepts, or relationship types
- low_level_keywords: specific entities, proper nouns, technical terms

Output a JSON object with exactly two keys: "high_level_keywords" and "low_level_keywords", each an array of strings. Output JSON only.

Examples:
Query: "What services depend on the authentication module?"
{{"high_level_keywords": ["service dependencies", "system architecture"], "low_level_keywords": ["authentication module"]}}

Query: "How has the deployment process changed since January?"
{{"high_level_keywords": ["process evolution", "deployment changes"], "low_level_keywords": ["deployment process", "January"]}}

Query: "What is the conversion rate formula?"
{{"high_level_keywords": ["metric definition", "business analytics"], "low_level_keywords": ["conversion rate", "formula"]}}

Query: "{query}"
"""


@dataclass
class QueryKeywords:
    high_level_keywords: list[str]
    low_level_keywords: list[str]


async def extract_query_keywords(
    client: AsyncAnthropic,
    query: str,
    model: str = "claude-3-5-haiku-20241022",
    timeout: float = 15.0,
) -> QueryKeywords:
    """Extract dual-level keywords from a user query via Claude."""
    prompt = KEYWORD_EXTRACTION_PROMPT.format(query=query)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        raw_text = response.content[0].text.strip()
        data = json.loads(raw_text)
        return QueryKeywords(
            high_level_keywords=data.get("high_level_keywords", []),
            low_level_keywords=data.get("low_level_keywords", []),
        )
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.warning("keyword_extraction_parse_failed", query=query[:100])
        raise
    except Exception:
        logger.warning("keyword_extraction_failed", query=query[:100], exc_info=True)
        raise
```

### Tool Definition
```python
# Addition to src/pam/agent/tools.py
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
        },
        "required": ["query"],
    },
}
```

### Config Settings
```python
# Additions to src/pam/common/config.py Settings class
smart_search_es_limit: int = 5
smart_search_graph_limit: int = 5
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate document + graph tool calls | Unified smart_search with dual-level keywords | LightRAG (EMNLP 2025, Oct 2024 preprint) | ~6000x fewer retrieval tokens vs GraphRAG; 1 tool call vs 2-3 |
| Single keyword extraction | Dual-level (high/low) keyword classification | LightRAG 2024 | High-level keywords find relationships, low-level find entities -- complementary coverage |
| Sequential search backends | Concurrent async search | Standard async Python pattern | ~50% latency reduction for 2 independent searches |

**Deprecated/outdated:**
- Single-query-to-all-backends approach (naive): LightRAG demonstrated that classifying query intent into entity vs theme keywords and routing to appropriate backends produces better results than sending the same query to all backends.

## Open Questions

1. **Haiku model ID for keyword extraction**
   - What we know: Claude 3.5 Haiku is fast and cheap, suitable for classification tasks. The existing `agent_model` setting uses Claude Sonnet.
   - What's unclear: Whether to hardcode the Haiku model ID or make it configurable via a new env var (e.g., `SMART_SEARCH_EXTRACTION_MODEL`).
   - Recommendation: Hardcode Haiku for now. If users need to change it, add the env var in a future iteration.

2. **Original query as implicit low-level keyword**
   - What we know: The user left this as Claude's discretion. Passing the original query alongside extracted keywords to ES ensures relevance even with poor extraction.
   - What's unclear: Whether this creates redundancy or improves recall.
   - Recommendation: Include the original query as the primary ES search query, with extracted low-level keywords appended. This is the safest approach and avoids the "empty keywords" pitfall.

3. **Keyword count caps**
   - What we know: LightRAG does not hardcode keyword count limits. The user left this as Claude's discretion.
   - What's unclear: Whether letting the LLM produce variable-length lists is better than capping at e.g., 3 high-level + 5 low-level.
   - Recommendation: Do not cap in the prompt. The `max_tokens=100` constraint naturally limits output length. If extraction produces too many keywords, address in Phase 15 (retrieval mode router).

## Sources

### Primary (HIGH confidence)
- LightRAG GitHub repository (HKUDS/LightRAG) -- `prompt.py` keyword extraction template, `operate.py` retrieval logic
- PAM codebase direct inspection -- `agent.py`, `tools.py`, `hybrid_search.py`, `query.py`, `config.py`, `entity_extractor.py`
- Anthropic SDK usage patterns from existing codebase

### Secondary (MEDIUM confidence)
- [Neo4j Blog: Under the Covers With LightRAG: Retrieval](https://neo4j.com/blog/developer/under-the-covers-with-lightrag-retrieval/) -- dual-level retrieval architecture
- [DeepWiki: LightRAG Query Processing](https://deepwiki.com/lanarich/LightRAG/2.3-query-processing) -- kg_query implementation flow
- [PromptEngineering.org: LightRAG Dual-Level Retrieval](https://promptengineering.org/lightrag-graph-enhanced-text-indexing-and-dual-level-retrieval/) -- high/low keyword classification rationale
- [Graphiti search documentation](https://help.getzep.com/graphiti/working-with-data/searching) -- search method parameters

### Tertiary (LOW confidence)
- LightRAG paper (arXiv 2410.05779) -- referenced but not directly fetched; claims about 6000x token reduction are from secondary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries are already installed and used in the project; no new dependencies
- Architecture: HIGH - pattern follows existing codebase conventions; all building blocks verified in source code
- Pitfalls: HIGH - identified from direct code analysis of asyncio.gather behavior, LLM call patterns, and existing dedup approach

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (stable -- no rapidly evolving dependencies)
