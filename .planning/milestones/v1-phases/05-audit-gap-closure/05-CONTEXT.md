# Phase 5: Audit Gap Closure - Context

**Gathered:** 2026-02-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Close all gaps identified by v1 milestone audit: fix mypy type errors in deps.py, add SearchService Protocol annotation to RetrievalAgent, remove dead frontend API functions, wire conversation_id through SSE and non-streaming paths, and align ChatResponse fields between backend and frontend.

</domain>

<decisions>
## Implementation Decisions

### conversation_id wiring
- Backend generates UUID on first turn (when `conversation_id` is null in the request)
- conversation_id returned as **top-level field** in SSE `done` event (not nested inside metadata)
- Also returned in non-streaming `ChatResponse`
- First message sends `conversation_id=null`, server generates and returns new ID
- Client sends conversation_id back on subsequent turns in the same conversation (hybrid stateless pattern)
- No server-side session state or DB persistence for conversations in this phase

### ChatResponse field alignment
- **Frontend changes to match backend** — backend shape is the source of truth
- Frontend `ChatResponse` interface updated to match backend: `{response, citations, conversation_id, token_usage, latency_ms}`
- The non-streaming fallback path in `useChat.ts` updated to read the correct field names
- `token_usage` and `latency_ms` fields wired through to the UI on both streaming and non-streaming paths

### Metrics display
- Token count and latency displayed on **both** streaming and non-streaming responses
- For streaming: read from SSE `done` event metadata (already has `token_usage` and `latency_ms`)
- For non-streaming: read directly from `ChatResponse` fields
- Display style: **expandable details** section below assistant messages (hidden by default, click to expand)
- Shows token breakdown (input/output/total) and latency

### Claude's Discretion
- Exact mypy `cast()` patterns for `app.state` accesses in deps.py
- SearchService Protocol design (already decided on Protocol over ABC in Phase 3)
- Expandable details component styling and animation
- How to store metrics in the messages state (likely extend ChatMessage type)

</decisions>

<specifics>
## Specific Ideas

- Industry trend is toward server-generated conversation IDs (OpenAI Responses API pattern)
- Hybrid pattern chosen: server generates ID, client echoes it back, server stays stateless
- conversation_id at top level of done event (not buried in metadata) for cleaner semantics
- Expandable details for metrics rather than always-visible footer — keeps chat clean

</specifics>

<deferred>
## Deferred Ideas

- **Conversation persistence to DB** — new conversations table to store conversation_id + message history. Enables server-side history retrieval. Significant new capability, its own phase.
- **Server-side session state** — Redis or DB session storage so server tracks conversation internally without client sending ID back each turn. Depends on conversation persistence.

</deferred>

---

*Phase: 05-audit-gap-closure*
*Context gathered: 2026-02-18*
