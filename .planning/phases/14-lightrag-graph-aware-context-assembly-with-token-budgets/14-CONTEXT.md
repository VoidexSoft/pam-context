# Phase 14: Graph-Aware Context Assembly with Token Budgets - Context

**Gathered:** 2025-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a 4-stage context assembly pipeline inside `smart_search` that takes raw retrieval results (entities, relationships, document chunks) and assembles them into structured, token-budgeted context blocks for the LLM agent. This is internal processing — users don't see it directly, but it determines the quality and structure of agent context.

</domain>

<decisions>
## Implementation Decisions

### Truncation Strategy
- Sort items by relevance score within each category; keep highest-scoring items first
- When an individual item's description is too long but high-relevance, truncate the description to a max token length (don't drop it entirely)
- Apply the same truncation logic uniformly across all three categories (entities, relationships, chunks)
- When items are truncated/dropped, append a count indicator (e.g., `[+3 more entities not shown]`) so the LLM knows context is incomplete

### Context Formatting
- Use Markdown sections with `##` headers per category: `## Knowledge Graph Entities`, `## Knowledge Graph Relationships`, `## Document Chunks`
- Entities formatted as bullet lists: `- **Entity Name**: description`
- Relationships use arrow notation: `**Entity A** → relates_to → **Entity B**: description`
- Document chunks include title + section source references: `[Source: Architecture Guide > Authentication Section]`
- Include a brief summary header before content blocks: `Found 5 relevant entities, 8 relationships, and 3 document chunks`

### Budget Allocation
- Default budgets: entities 4000 tokens, relationships 6000 tokens, chunks dynamic (total minus others)
- Default `max_context_tokens`: 12000 (global config only, not per-query)
- Unused budget from sparse categories redistributes to chunks (the dynamic category)
- Token counting via tiktoken with cl100k_base encoding (Claude-compatible)

### Edge Cases & Fallbacks
- Omit empty categories entirely (don't show headers with "None found")
- Deduplicate chunks by chunk ID when the same chunk appears via entity-sourced and relationship-sourced results; keep one copy in Document Chunks section
- When all categories return zero results, return a simple note: "No relevant context found in knowledge base"
- Log token budget usage per category at DEBUG level via structlog (e.g., `entities: 2100/4000 tokens`)

### Claude's Discretion
- Exact max token length for individual item description truncation
- Internal data structures for the 4-stage pipeline
- How chunk dedup tracks provenance metadata
- tiktoken integration approach (lazy loading, caching, etc.)

</decisions>

<specifics>
## Specific Ideas

- Pipeline inspired by LightRAG's `_build_query_context()` 4-stage approach: search → truncate → merge chunks → build context string
- Context assembly happens inside `smart_search` before returning to the agent, not as a separate tool call
- Structured logging should use the project's existing structlog patterns with correlation IDs

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 14-lightrag-graph-aware-context-assembly-with-token-budgets*
*Context gathered: 2025-02-25*
