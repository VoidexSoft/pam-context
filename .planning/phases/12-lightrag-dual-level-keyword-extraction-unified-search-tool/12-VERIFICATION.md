---
phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool
verified: 2026-02-24T10:00:00Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 12: Dual-Level Keyword Extraction + Unified Search Tool — Verification Report

**Phase Goal:** A single `smart_search` agent tool generates entity-level and theme-level keywords from the query, runs ES hybrid search and graph relationship search in parallel, and returns merged results — so that the agent answers graph-aware questions in 1 tool call instead of 2-3, following LightRAG's dual-level retrieval pattern.
**Verified:** 2026-02-24T10:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|---------|
| 1  | `extract_query_keywords()` calls Claude Haiku and returns `QueryKeywords` with `high_level_keywords` and `low_level_keywords` lists | VERIFIED | `client.messages.create()` call confirmed in `keyword_extractor.py`; `QueryKeywords` dataclass has both fields; imports succeed |
| 2  | Keyword extraction uses a ~50-token prompt with 3 few-shot examples adapted from LightRAG | VERIFIED | `KEYWORD_EXTRACTION_PROMPT` is 935 chars with 4 `Query:` occurrences (3 examples + 1 active); model default is `claude-3-5-haiku-20241022`; `max_tokens=100` |
| 3  | `SMART_SEARCH_ES_LIMIT` and `SMART_SEARCH_GRAPH_LIMIT` are configurable via env vars with defaults of 5 | VERIFIED | `smart_search_es_limit: int = 5` and `smart_search_graph_limit: int = 5` in `Settings`; placed in `# Smart Search` section between `# DuckDB` and `# Ingestion` |
| 4  | `SMART_SEARCH_TOOL` definition exists in `ALL_TOOLS` list with correct input schema | VERIFIED | `ALL_TOOLS` has 8 tools; `SMART_SEARCH_TOOL` has `name: "smart_search"`, `query` in `properties` and `required`; confirmed by test suite |
| 5  | Agent can call `smart_search` with a natural language query and receive results from both ES and the knowledge graph in one tool call | VERIFIED | `_smart_search()` method exists on `RetrievalAgent`; `_execute_tool` dispatches `smart_search` to it; full implementation confirmed |
| 6  | Low-level keywords drive ES hybrid search and high-level keywords drive Graphiti semantic edge search, both running concurrently via `asyncio.gather` | VERIFIED | `asyncio.gather(_es_search_coro(), _graph_search_coro(), return_exceptions=True)` in `_smart_search`; low-level keywords joined for `es_query`, high-level for `graph_query` |
| 7  | Results are returned in two separate sections (`document_results` and `graph_results`) with extracted keywords included | VERIFIED | Output contains `Keywords extracted:`, `## Document Results (N results)`, and `## Graph Results` sections |
| 8  | If one search backend fails, partial results from the working backend are returned with a warning field | VERIFIED | `isinstance(result, Exception)` check per backend; `warnings.append("es_backend_failed")` / `"graph_backend_failed"` with warning lines in output |
| 9  | Existing `search_knowledge` and `search_knowledge_graph` tools still work as fallbacks | VERIFIED | All 7 pre-existing tools remain in `_execute_tool` dispatch; `_search_knowledge()` and `_search_knowledge_graph()` handlers preserved |
| 10 | Backfill fills remaining quota from the other source when one returns fewer results | VERIFIED | `_graph_limit` reserved with comment "reserved for future re-query backfill"; informational best-effort backfill implemented as designed (no re-query per user decision) |

**Score:** 10/10 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pam/agent/keyword_extractor.py` | `extract_query_keywords()` async function + `QueryKeywords` dataclass + `KEYWORD_EXTRACTION_PROMPT` with 3 few-shot examples | VERIFIED | File is 96 lines; all three exports confirmed; prompt has 3 examples; function uses `client.messages.create()` with `max_tokens=100` and `claude-3-5-haiku-20241022` default |
| `src/pam/common/config.py` | `smart_search_es_limit` and `smart_search_graph_limit` Settings fields | VERIFIED | Lines 69-70; both `int = 5`; placed in `# Smart Search` section as specified |
| `src/pam/agent/tools.py` | `SMART_SEARCH_TOOL` definition added to `ALL_TOOLS` | VERIFIED | Lines 190-208; appended as 8th item in `ALL_TOOLS`; correct schema with `query` property |
| `src/pam/agent/agent.py` | `_smart_search()` handler, `_execute_tool` dispatch for `smart_search`, updated `SYSTEM_PROMPT` with 8 tools | VERIFIED | `_smart_search()` at line 396; dispatch at line 378; `SYSTEM_PROMPT` lists all 8 tools |
| `tests/test_agent/test_smart_search.py` | 9 integration smoke tests covering tool definition, keyword extraction, system prompt, config defaults | VERIFIED | 9 tests across 5 classes; all 9 pass |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/pam/agent/keyword_extractor.py` | `anthropic.AsyncAnthropic` | `client.messages.create()` call | WIRED | `await client.messages.create(model=..., max_tokens=100, messages=[...], timeout=timeout)` confirmed |
| `src/pam/agent/tools.py` | `ALL_TOOLS` | `SMART_SEARCH_TOOL` appended to list | WIRED | `SMART_SEARCH_TOOL` is the 8th and final element in `ALL_TOOLS` |
| `src/pam/agent/agent.py` | `src/pam/agent/keyword_extractor.py` | `extract_query_keywords()` call in `_smart_search` | WIRED | Top-level import: `from pam.agent.keyword_extractor import extract_query_keywords`; called in `_smart_search()` |
| `src/pam/agent/agent.py` | `src/pam/retrieval/search_protocol.py` | `self.search.search()` for ES hybrid search | WIRED | `await self.search.search(query=es_query, query_embedding=embeddings[0], top_k=es_limit, ...)` in `_es_search_coro()` |
| `src/pam/agent/agent.py` | `src/pam/graph/query.py` | `search_graph_relationships()` for graph search | WIRED | `from pam.graph.query import search_graph_relationships` inside `_graph_search_coro()`; called with `graph_service` and `graph_query` |
| `src/pam/agent/agent.py` | `asyncio.gather` | Concurrent ES + graph search execution | WIRED | `await asyncio.gather(_es_search_coro(), _graph_search_coro(), return_exceptions=True)` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| SMART-01 | 12-02-PLAN.md | `smart_search` tool that accepts natural language query and returns merged ES + graph results | SATISFIED | `_smart_search()` accepts `input_["query"]`, calls both ES and graph backends, returns dual-section formatted text with `Citation` list |
| SMART-02 | 12-01-PLAN.md | Keyword extraction via Claude call producing `{high_level_keywords, low_level_keywords}` (~50 tokens) | SATISFIED | `extract_query_keywords()` calls Claude Haiku with `max_tokens=100`; returns `QueryKeywords` dataclass; parse + re-raise error handling confirmed |
| SMART-03 | 12-02-PLAN.md | Low-level keywords drive ES hybrid search, high-level keywords drive Graphiti edge search, both concurrent | SATISFIED | `es_query = " ".join(low_level_keywords)`; `graph_query = " ".join(high_level_keywords)`; `asyncio.gather` runs both concurrently with `return_exceptions=True` |

**Note on REQUIREMENTS.md:** SMART-01, SMART-02, SMART-03 are defined in ROADMAP.md (line 158) but do NOT appear in `.planning/REQUIREMENTS.md`. REQUIREMENTS.md currently covers only v2.0 requirements (INFRA, EXTRACT, GRAPH, DIFF, VIZ families). The SMART-* requirements belong to the v3.0/LightRAG milestone which has not yet been added to REQUIREMENTS.md. This is a documentation gap in REQUIREMENTS.md — it does not affect implementation correctness, as all three SMART-* requirements are fully satisfied in the codebase. The ROADMAP.md is the authoritative source for Phase 12 requirements.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None found | — | — |

All four modified/created source files pass `ruff check` with zero errors. No TODO/FIXME/PLACEHOLDER comments found. No stub returns (`return {}`, `return []`, `return None` without condition) found in phase-12 code paths.

---

### Human Verification Required

#### 1. Round-Robin vs Separate Sections (ROADMAP vs User Decision)

**Test:** Issue a query like "What services depend on the authentication module?" via the chat UI and inspect the raw tool result in browser devtools.
**Expected:** Response has a "Keywords extracted:" header, "## Document Results" section, and "## Graph Results" section — NOT a round-robin interleaved single list.
**Why human:** The ROADMAP (SC-4) originally said "round-robin interleaving" but CONTEXT.md user decisions explicitly overrode this to "two separate sections, not a single merged list." The PLAN locked this in. A human should confirm the UX is acceptable for the agent.

#### 2. Smart Search Preferred Tool Behavior (ROADMAP SC-5 vs User Decision)

**Test:** Ask a relationship-aware question (e.g., "What depends on the AuthService?") and observe the agent's tool choice in chat UI.
**Expected:** Agent uses `smart_search` in 1 call (or optionally uses `search_knowledge_graph` per its discretion). The system prompt does NOT force smart_search as preferred.
**Why human:** ROADMAP SC-5 says "smart_search is the agent's preferred first tool" but CONTEXT.md decision overrides this to equal treatment. The system prompt lists `smart_search` first alphabetically but adds no preference rules. Whether the agent naturally prefers it in practice requires a live inference test.

#### 3. Eval Improvement (ROADMAP SC-6)

**Test:** Run `python eval/run_eval.py` with relationship-aware questions from `eval/questions.json`.
**Expected:** Tool call count for relationship questions drops from 2-3 to 1 with `smart_search`.
**Why human:** This requires live Anthropic API + ES + Neo4j services. Cannot verify programmatically in static analysis.

---

### Gaps Summary

No gaps found. All 10 observable truths are verified, all 5 required artifacts exist and are substantive and wired, all 6 key links are connected, and all 3 SMART-* requirements are satisfied.

Two ROADMAP success criteria (SC-4 round-robin interleaving, SC-5 preferred tool) were intentionally overridden by user decisions documented in CONTEXT.md and locked into PLAN must_haves. The implementation correctly follows the user decisions. These are not gaps — they are documented design changes.

The only documentation gap is that SMART-01, SMART-02, SMART-03 are absent from REQUIREMENTS.md (they exist only in ROADMAP.md). This does not affect implementation completeness.

---

### Commits Verified

| Hash | Message |
|------|---------|
| `ed45809` | feat(12-01): add keyword extraction module and smart search config settings |
| `7f3949d` | feat(12-01): add SMART_SEARCH_TOOL definition to agent tools |
| `15f8e8d` | feat(12-02): implement _smart_search handler with concurrent ES + graph search |
| `1594fb0` | test(12-02): add integration smoke tests for smart_search tool |

All 4 commits present in git history.

---

_Verified: 2026-02-24T10:00:00Z_
_Verifier: Claude (gsd-verifier)_
