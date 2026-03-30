# Phase 14: Graph-Aware Context Assembly with Token Budgets - Research

**Researched:** 2026-02-25
**Domain:** LLM context assembly, token budgeting, structured prompt construction
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Truncation Strategy:** Sort items by relevance score within each category; keep highest-scoring items first. When an individual item's description is too long but high-relevance, truncate the description to a max token length (don't drop it entirely). Apply the same truncation logic uniformly across all three categories. When items are truncated/dropped, append a count indicator (e.g., `[+3 more entities not shown]`) so the LLM knows context is incomplete.
- **Context Formatting:** Use Markdown sections with `##` headers per category: `## Knowledge Graph Entities`, `## Knowledge Graph Relationships`, `## Document Chunks`. Entities formatted as bullet lists: `- **Entity Name**: description`. Relationships use arrow notation: `**Entity A** -> relates_to -> **Entity B**: description`. Document chunks include title + section source references: `[Source: Architecture Guide > Authentication Section]`. Include a brief summary header before content blocks: `Found 5 relevant entities, 8 relationships, and 3 document chunks`.
- **Budget Allocation:** Default budgets: entities 4000 tokens, relationships 6000 tokens, chunks dynamic (total minus others). Default `max_context_tokens`: 12000 (global config only, not per-query). Unused budget from sparse categories redistributes to chunks (the dynamic category). Token counting via tiktoken with cl100k_base encoding (Claude-compatible).
- **Edge Cases & Fallbacks:** Omit empty categories entirely (don't show headers with "None found"). Deduplicate chunks by chunk ID when the same chunk appears via entity-sourced and relationship-sourced results; keep one copy in Document Chunks section. When all categories return zero results, return a simple note: "No relevant context found in knowledge base". Log token budget usage per category at DEBUG level via structlog.

### Claude's Discretion
- Exact max token length for individual item description truncation
- Internal data structures for the 4-stage pipeline
- How chunk dedup tracks provenance metadata
- tiktoken integration approach (lazy loading, caching, etc.)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CTX-01 | Context assembly follows a 4-stage pipeline: (1) raw retrieval, (2) per-category token truncation, (3) chunk dedup and merge, (4) structured prompt construction | LightRAG `_build_query_context()` 4-stage pattern documented; `truncate_list_by_token_size()` pattern verified in source; current `_smart_search` in `agent.py` provides the insertion point |
| CTX-02 | Token budgets are configurable: entity descriptions (default 4000), relationship descriptions (default 6000), source chunks (dynamic: total budget minus other categories) | LightRAG uses 6000/8000/30000 defaults; user decided 4000/6000/12000 for PAM; tiktoken cl100k_base is the chosen tokenizer; Settings pattern in `config.py` supports new env vars |
| CTX-03 | Agent's system prompt includes structured context blocks: `## Knowledge Graph Entities`, `## Knowledge Graph Relationships`, `## Document Chunks` with source references | Current `_smart_search` output already has 4 sections (`Document Results`, `Graph Results`, `Entity Matches`, `Relationship Matches`); phase refactors these into the 3 user-specified categories with proper formatting |
</phase_requirements>

## Summary

Phase 14 transforms `smart_search`'s raw result concatenation into a structured, token-budgeted context assembly pipeline. The current implementation in `src/pam/agent/agent.py` (`_smart_search` method, lines 401-595) simply formats and joins all search results without any token limit awareness. This phase adds a 4-stage pipeline between raw retrieval and the final tool result string: (1) collect raw results from all 4 search backends, (2) sort by relevance and truncate each category to its token budget, (3) deduplicate chunks that appear across multiple result sources, and (4) construct a structured Markdown prompt with `##` headers per category.

The core dependency is **tiktoken** (v0.12.0) with `cl100k_base` encoding for token counting. While this encoding is technically OpenAI's, it provides a reasonable approximation for Claude token counts and is the user's explicit choice. The token counting function itself is trivial -- `len(enc.encode(text))` -- but the pipeline design matters: categories must be truncated independently, unused budget should redistribute to chunks, and individual item descriptions should be truncated (not dropped) when they exceed a per-item limit.

**Primary recommendation:** Create a standalone `context_assembly.py` module in `src/pam/agent/` that exports a single `assemble_context()` function. This function takes the 4 raw result sets (ES results, graph text, entity VDB results, relationship VDB results) plus budget config, and returns the final formatted string. The `_smart_search` method calls this function instead of doing its own formatting. This keeps the assembly logic testable in isolation.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tiktoken | 0.12.0 | BPE token counting | De facto standard for offline token counting in Python; Rust-backed for speed; `cl100k_base` encoding is user's locked choice |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 24.x (already installed) | DEBUG-level budget usage logging | For the `entities: 2100/4000 tokens` log lines per user decision |
| pydantic-settings | 2.x (already installed) | Config env vars for budget defaults | For `CONTEXT_ENTITY_BUDGET`, `CONTEXT_RELATIONSHIP_BUDGET`, `CONTEXT_MAX_TOKENS` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tiktoken | Anthropic Token Count API | More accurate for Claude but requires API call (network latency + cost); tiktoken is offline and fast (~1ms for 12K tokens) |
| tiktoken | Simple `len(text) // 4` heuristic | Faster but inaccurate by 15-25%; user explicitly chose tiktoken |
| New module | Inline in `_smart_search` | Keeps code in one place but `_smart_search` is already 195 lines; separate module enables unit testing |

**Installation:**
```bash
pip install tiktoken>=0.12
```
Add `"tiktoken>=0.12"` to `pyproject.toml` dependencies.

## Architecture Patterns

### Recommended Project Structure
```
src/pam/agent/
├── agent.py                  # _smart_search calls assemble_context()
├── context_assembly.py       # NEW: 4-stage pipeline + token counting
├── keyword_extractor.py      # Existing: keyword extraction
├── tools.py                  # Existing: tool definitions
└── duckdb_service.py         # Existing: DuckDB analytics
```

### Pattern 1: Token-Budgeted Truncation (from LightRAG)
**What:** Iterate through a relevance-sorted list, accumulating token counts. Stop adding items when budget is exhausted. If a single item exceeds a per-item cap, truncate its text content rather than dropping it entirely.
**When to use:** Every category (entities, relationships, chunks) during stage 2.
**Example:**
```python
# Adapted from LightRAG truncate_list_by_token_size
import tiktoken

_encoder: tiktoken.Encoding | None = None

def _get_encoder() -> tiktoken.Encoding:
    """Lazy-load and cache the tiktoken encoder (singleton)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder

def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding."""
    return len(_get_encoder().encode(text))

def truncate_list_by_token_budget(
    items: list[dict],
    text_key: str,
    max_tokens: int,
    max_item_tokens: int = 500,
) -> tuple[list[dict], int]:
    """Truncate a sorted list of items to fit within a token budget.

    Returns (truncated_items, tokens_used).
    Items whose text exceeds max_item_tokens have their text truncated.
    """
    result = []
    tokens_used = 0
    for item in items:
        text = item[text_key]
        item_tokens = count_tokens(text)

        # Truncate individual item if too long
        if item_tokens > max_item_tokens:
            text = _truncate_text_to_tokens(text, max_item_tokens)
            item_tokens = max_item_tokens
            item = {**item, text_key: text}  # copy with truncated text

        if tokens_used + item_tokens > max_tokens:
            break

        result.append(item)
        tokens_used += item_tokens

    return result, tokens_used
```

### Pattern 2: Budget Redistribution
**What:** After truncating entities and relationships to their fixed budgets, calculate unused budget and add it to the chunk budget. This maximizes context utilization when one category has sparse results.
**When to use:** Stage 2, after entity and relationship truncation.
**Example:**
```python
def calculate_chunk_budget(
    max_total: int,
    entity_budget: int,
    relationship_budget: int,
    entity_tokens_used: int,
    relationship_tokens_used: int,
) -> int:
    """Calculate chunk budget including unused redistribution."""
    # Base chunk budget = total - fixed budgets
    base_chunk_budget = max_total - entity_budget - relationship_budget
    # Add back unused from entities and relationships
    unused = (entity_budget - entity_tokens_used) + (relationship_budget - relationship_tokens_used)
    return base_chunk_budget + unused
```

### Pattern 3: Structured Context Block Construction
**What:** Build the final Markdown string with category headers, summary line, formatted items, and truncation indicators.
**When to use:** Stage 4 of the pipeline.
**Example:**
```python
def build_context_string(
    entities: list[dict],
    relationships: list[dict],
    chunks: list[dict],
    total_entities: int,
    total_relationships: int,
    total_chunks: int,
) -> str:
    """Build structured context string with Markdown headers."""
    parts = []

    # Summary header
    parts.append(
        f"Found {total_entities} relevant entities, "
        f"{total_relationships} relationships, and "
        f"{total_chunks} document chunks"
    )
    parts.append("")

    # Entities section (omit if empty)
    if entities:
        parts.append("## Knowledge Graph Entities")
        for e in entities:
            parts.append(f"- **{e['name']}**: {e['description']}")
        dropped = total_entities - len(entities)
        if dropped > 0:
            parts.append(f"[+{dropped} more entities not shown]")
        parts.append("")

    # Relationships section (omit if empty)
    if relationships:
        parts.append("## Knowledge Graph Relationships")
        for r in relationships:
            parts.append(
                f"**{r['src_entity']}** -> {r['rel_type']} -> "
                f"**{r['tgt_entity']}**: {r['description']}"
            )
        dropped = total_relationships - len(relationships)
        if dropped > 0:
            parts.append(f"[+{dropped} more relationships not shown]")
        parts.append("")

    # Chunks section (omit if empty)
    if chunks:
        parts.append("## Document Chunks")
        for c in chunks:
            source_ref = c.get("source_label", "Unknown")
            parts.append(f"[Source: {source_ref}]")
            parts.append(c["content"])
            parts.append("")

    if not entities and not relationships and not chunks:
        return "No relevant context found in knowledge base"

    return "\n".join(parts)
```

### Pattern 4: Chunk Deduplication by ID
**What:** ES segment results and VDB-sourced results may reference the same underlying document chunks. Deduplicate by `segment_id` (for ES results) or content hash before including in the chunks section.
**When to use:** Stage 3, after truncation but before final assembly.
**Example:**
```python
def deduplicate_chunks(chunks: list[dict], key: str = "segment_id") -> list[dict]:
    """Remove duplicate chunks by key, preserving order (first occurrence wins)."""
    seen: set[str] = set()
    result = []
    for chunk in chunks:
        chunk_key = str(chunk.get(key, ""))
        if chunk_key and chunk_key in seen:
            continue
        seen.add(chunk_key)
        result.append(chunk)
    return result
```

### Anti-Patterns to Avoid
- **Token counting on every format iteration:** Count tokens on the raw content before formatting, not on the formatted Markdown string. Formatting adds headers/bullets that inflate token count unpredictably.
- **Global truncation instead of per-category:** Truncating the entire output string at the end loses structure. Always truncate per-category first, then assemble.
- **Blocking on tiktoken download:** The first call to `tiktoken.get_encoding()` downloads the encoding data. Use lazy loading with a module-level singleton to avoid blocking at import time.
- **Dropping the existing graph_text format:** The current `search_graph_relationships` returns pre-formatted text. For Phase 14, the VDB relationship results (structured dicts) should be formatted using the new arrow notation, but graph_text from Graphiti search should be included as supplementary context within the relationships section rather than reformatted.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token counting | Character-based estimation (`len(text) // 4`) | `tiktoken` with `cl100k_base` | BPE tokenization is non-linear; a 1000-char string can be 200-400 tokens depending on content; tiktoken is Rust-backed and handles edge cases |
| BPE encoding | Custom tokenizer | `tiktoken.get_encoding("cl100k_base")` | Encoding tables are complex; tiktoken's Rust implementation is ~3-5x faster than pure Python alternatives |

**Key insight:** The token counting itself is trivial (one function call). The complexity is in the pipeline design: ordering truncation steps correctly, handling budget redistribution, and maintaining the information hierarchy so the LLM receives the most relevant context first.

## Common Pitfalls

### Pitfall 1: tiktoken First-Call Network Dependency
**What goes wrong:** `tiktoken.get_encoding("cl100k_base")` downloads encoding data on first call if not cached locally. In Docker/CI environments without network access, this fails silently or raises.
**Why it happens:** tiktoken lazily fetches BPE merge tables from a CDN.
**How to avoid:** (a) Pre-download during Docker build: `python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"`. (b) Use the lazy singleton pattern so the download happens once at first use, not at import time. (c) In tests, mock `count_tokens` to avoid the dependency entirely.
**Warning signs:** Tests that pass locally but fail in CI; slow first request after deployment.

### Pitfall 2: Budget Redistribution Double-Counting
**What goes wrong:** When redistributing unused entity/relationship budget to chunks, accidentally counting the header/formatting tokens as part of the budget, leaving less room for actual content.
**Why it happens:** Formatting tokens (headers, bullets, source references) add ~50-100 tokens per category.
**How to avoid:** Budget applies to content text only. Calculate formatting overhead separately as a small constant buffer (e.g., reserve 200 tokens for all formatting). Or count total after assembly and trim if over.
**Warning signs:** Chunk section consistently shorter than expected; total context consistently under budget.

### Pitfall 3: Graph Text Format Mismatch
**What goes wrong:** The existing `search_graph_relationships()` returns pre-formatted text with its own formatting (bullet points, source citations). If this gets mixed into the relationship VDB results, formatting becomes inconsistent.
**Why it happens:** Two different result formats: VDB search returns structured dicts, Graphiti search returns a string.
**How to avoid:** Keep graph_text as supplementary content appended after the structured VDB relationship items. Or parse graph_text back into structured items (fragile). Recommended: include graph_text as a sub-section or append it after the formatted VDB relationships.
**Warning signs:** Duplicate relationship information between graph_text and VDB results; inconsistent formatting in the relationships section.

### Pitfall 4: Empty Result Formatting Edge Cases
**What goes wrong:** The summary header says "Found 5 entities, 0 relationships, 3 chunks" but then the relationships section is omitted (per user decision to omit empty categories). This creates a mismatch.
**Why it happens:** Summary is generated before filtering, headers are generated after.
**How to avoid:** Generate the summary line AFTER determining which categories are non-empty. Only mention non-empty categories in the summary.
**Warning signs:** Summary mentions categories that don't appear in the output.

### Pitfall 5: Truncation Indicator Off-by-One
**What goes wrong:** The `[+3 more entities not shown]` count is wrong because it counts total items minus shown items, but some items were merged (deduplicated) before display.
**Why it happens:** Dedup happens in stage 3, truncation in stage 2. The "total" count comes from pre-dedup data.
**How to avoid:** Track `total_before_truncation` (from raw retrieval) separately from `shown_after_truncation`. The indicator should be `total_raw - shown`.
**Warning signs:** Indicator says "+0 more" when items were actually dropped.

## Code Examples

### Complete 4-Stage Pipeline Function
```python
# Source: Adapted from LightRAG _build_query_context pattern + user decisions
from dataclasses import dataclass

@dataclass
class ContextBudget:
    """Token budget configuration for context assembly."""
    entity_tokens: int = 4000
    relationship_tokens: int = 6000
    max_total_tokens: int = 12000
    max_item_tokens: int = 500  # per-item truncation cap

@dataclass
class AssembledContext:
    """Result of context assembly pipeline."""
    text: str
    entity_tokens_used: int
    relationship_tokens_used: int
    chunk_tokens_used: int
    total_tokens: int

def assemble_context(
    es_results: list,         # SearchResult objects from ES
    graph_text: str,          # Pre-formatted Graphiti search text
    entity_vdb_results: list, # Dicts from entity VDB search
    rel_vdb_results: list,    # Dicts from relationship VDB search
    budget: ContextBudget | None = None,
) -> AssembledContext:
    """4-stage context assembly pipeline.

    Stage 1: Collect and normalize raw results
    Stage 2: Per-category token truncation (sorted by relevance score)
    Stage 3: Chunk dedup and merge
    Stage 4: Structured prompt construction
    """
    budget = budget or ContextBudget()
    # ... implementation per patterns above
```

### tiktoken Lazy Singleton
```python
# Source: tiktoken GitHub README + project pattern
import tiktoken

_encoder: tiktoken.Encoding | None = None

def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder

def count_tokens(text: str) -> int:
    return len(_get_encoder().encode(text))
```

### Config Settings Extension
```python
# Source: Existing config.py pattern in src/pam/common/config.py
class Settings(BaseSettings):
    # ... existing fields ...

    # Context Assembly Token Budgets
    context_entity_budget: int = 4000
    context_relationship_budget: int = 6000
    context_max_tokens: int = 12000
```

### structlog Budget Logging
```python
# Source: Existing structlog pattern in agent.py
logger.debug(
    "context_assembly_budget",
    entities=f"{entity_tokens_used}/{budget.entity_tokens}",
    relationships=f"{rel_tokens_used}/{budget.relationship_tokens}",
    chunks=f"{chunk_tokens_used}/{chunk_budget}",
    total=f"{total_tokens}/{budget.max_total_tokens}",
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Concatenate all results into one string | Token-budgeted per-category truncation | LightRAG (EMNLP 2025) | ~6,000x fewer retrieval tokens than GraphRAG with comparable quality |
| Fixed result count limits | Token-based budget with redistribution | LightRAG constants module | Adapts to variable item sizes; short entity descriptions leave room for more chunks |
| Single "context" block | Structured categories with Markdown headers | Industry standard for tool-use agents | LLM can selectively attend to relevant category; improves citation accuracy |

**Deprecated/outdated:**
- Simple character-based truncation: Token counts are non-linear with character counts for BPE encoders. Always use proper tokenizer.
- Per-result-count limits (top_k only): A result with 500 tokens of content and one with 50 tokens consume the same "slot" under top_k, but vastly different token budget. Token-based budgeting is strictly better.

## Open Questions

1. **How to handle graph_text from Graphiti search in the relationships section**
   - What we know: Graphiti search returns pre-formatted text; VDB relationship results are structured dicts. Both contain relationship information.
   - What's unclear: Should graph_text be parsed into structured items, appended verbatim as a sub-section, or should the Graphiti results be skipped in favor of VDB results only?
   - Recommendation: Append graph_text as supplementary content after the formatted VDB relationships, within the same `## Knowledge Graph Relationships` section. This avoids fragile parsing while preserving all relationship context. Count its tokens toward the relationship budget.

2. **Per-item token truncation limit**
   - What we know: User decided items should be truncated (not dropped) when too long. Exact limit is Claude's discretion.
   - What's unclear: Optimal per-item limit depends on typical entity/relationship description lengths in the knowledge base.
   - Recommendation: Default to **500 tokens** per item. This accommodates detailed descriptions (~375 words) while preventing a single verbose entity from consuming the entire category budget. Make it configurable but not exposed as an env var (internal constant).

3. **Interaction with existing tool result size cap (GRAPH-06: 3000 chars)**
   - What we know: Phase 8 introduced a 3000-char hard cap on graph tool results. smart_search is a separate tool with its own result formatting.
   - What's unclear: Should the context assembly respect the 3000-char cap, or does the token budget (12000 tokens ~ 48000 chars) supersede it?
   - Recommendation: The token budget supersedes the char cap for smart_search. The 3000-char cap applies only to `search_knowledge_graph` and `get_entity_history` (dedicated graph tools). smart_search has its own budget system.

## Sources

### Primary (HIGH confidence)
- [tiktoken GitHub](https://github.com/openai/tiktoken) - v0.12.0, cl100k_base encoding, Rust BPE implementation
- [tiktoken PyPI](https://pypi.org/project/tiktoken/) - Latest release: 0.12.0 (October 2025), Python >=3.9
- Existing codebase: `src/pam/agent/agent.py` - Current `_smart_search` implementation (lines 401-595)
- Existing codebase: `src/pam/common/config.py` - Settings pattern for new env vars
- Existing codebase: `src/pam/ingestion/stores/entity_relationship_store.py` - VDB search return formats

### Secondary (MEDIUM confidence)
- [LightRAG GitHub (HKUDS)](https://github.com/HKUDS/LightRAG) - 4-stage context pipeline pattern, `truncate_list_by_token_size()` implementation in `lightrag/utils.py`
- [LightRAG constants.py](https://github.com/HKUDS/LightRAG/blob/main/lightrag/constants.py) - DEFAULT_MAX_ENTITY_TOKENS=6000, DEFAULT_MAX_RELATION_TOKENS=8000, DEFAULT_MAX_TOTAL_TOKENS=30000
- [LightRAG Query Processing (DeepWiki)](https://deepwiki.com/lanarich/LightRAG/2.3-query-processing) - 4-stage pipeline architecture documentation

### Tertiary (LOW confidence)
- [Claude Token Counting Docs](https://platform.claude.com/docs/en/build-with-claude/token-counting) - Anthropic's official token counting API (not used here, but noted as alternative)
- [Token Counting Guide 2025](https://www.propelcode.ai/blog/token-counting-tiktoken-anthropic-gemini-guide-2025) - Cross-model token counting comparison; notes tiktoken is approximate for Claude

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - tiktoken is well-established, user explicitly chose it, version verified on PyPI
- Architecture: HIGH - 4-stage pipeline pattern is well-documented in LightRAG; current codebase provides clear insertion point in `_smart_search`
- Pitfalls: HIGH - tiktoken network dependency is well-known; budget redistribution logic is straightforward; edge cases identified from existing code review

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable domain; tiktoken and LightRAG patterns unlikely to change)
