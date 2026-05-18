# Agent Latency Instrumentation — Design

**Date:** 2026-05-19
**Status:** Draft
**Owner:** felixngd

## Problem

End-to-end `/chat` request latency is 15–16s from question submit to first token. The cause is not yet measured. The `RetrievalAgent` runs a chain of LLM calls, embeddings, search backends, and tool turns; any one of them could dominate. Optimization without measurement is guessing.

## Goal

Add per-step timing instrumentation across the retrieval agent so a single sample query produces a structured log trail showing exactly where wall-clock time is spent. **This spec covers instrumentation only.** A follow-up spec will propose targeted fixes once real numbers are in hand.

## Non-Goals

- Performance fixes (prompt caching, parallelization, streaming changes, model right-sizing). These wait for data.
- A metrics endpoint, dashboard, or aggregation pipeline. Manual log grep is sufficient for first iteration.
- OpenTelemetry / distributed tracing infrastructure.
- Latency budgets, alerting, or SLOs.

## Architecture

A single new module — `src/pam/common/timing.py` — provides one async context manager (`timed_step`) and one sync context manager (`timed_block`). Both log a `step_<name>` structlog event on exit with `duration_ms`. The existing structlog middleware already injects `correlation_id` via contextvars, so all timing events for a single request share the same correlation ID with zero call-site work.

Instrumentation is added inline to:

- `src/pam/agent/agent.py` — `answer()`, `answer_streaming()`, `_smart_search()`, `_search_knowledge()`, `_fetch_user_context()`, `_execute_tool()` dispatch.
- `src/pam/agent/keyword_extractor.py` — `extract_query_keywords()`.
- `src/pam/agent/query_classifier.py` — `classify_query_mode()`, `_rule_based_classify()`, `_check_entity_mentions()`, `_llm_classify()`.
- `src/pam/retrieval/hybrid_search.py` — `HybridSearchService.search()` body (already has an end-of-call log; this adds duration and entry-point timing).

No new third-party dependencies. No config flag — instrumentation is always on; logs are cheap and structlog filtering handles volume in production.

## Components

### `pam/common/timing.py`

```python
"""Lightweight async/sync context managers for step timing."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator

import structlog


@asynccontextmanager
async def timed_step(
    logger: structlog.stdlib.BoundLogger,
    step: str,
    **fields: Any,
) -> AsyncIterator[dict[str, float]]:
    """Time an async block. Logs `step_<step>` on success, `step_<step>_failed` on exception.

    Yields a dict with `duration_ms` populated on exit, so callers can attach the
    measurement to a response object if needed. Always re-raises exceptions.
    """
    span: dict[str, float] = {"duration_ms": 0.0}
    t0 = time.perf_counter()
    try:
        yield span
    except Exception:
        span["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        logger.warning(
            f"step_{step}_failed",
            duration_ms=span["duration_ms"],
            **fields,
            exc_info=True,
        )
        raise
    else:
        span["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(f"step_{step}", duration_ms=span["duration_ms"], **fields)


@contextmanager
def timed_block(
    logger: structlog.stdlib.BoundLogger,
    step: str,
    **fields: Any,
) -> Iterator[dict[str, float]]:
    """Synchronous twin of `timed_step` for sync code paths (e.g. regex classifier)."""
    span: dict[str, float] = {"duration_ms": 0.0}
    t0 = time.perf_counter()
    try:
        yield span
    except Exception:
        span["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        logger.warning(
            f"step_{step}_failed",
            duration_ms=span["duration_ms"],
            **fields,
            exc_info=True,
        )
        raise
    else:
        span["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(f"step_{step}", duration_ms=span["duration_ms"], **fields)
```

### Instrumentation Map

Each row is one instrumentation site. The `step` name is the value logged as `step_<step>`. Bind the extra fields shown.

| Step name | File | Async | Extra fields |
|-----------|------|-------|--------------|
| `total_answer` | agent.py `answer()` and `answer_streaming()` | yes | `streaming` (bool), `total_input_tokens`, `total_output_tokens`, `tool_calls`, `iterations` (set on exit via the yielded dict) |
| `keyword_extraction` | keyword_extractor.py | yes | `query_len`, `keyword_count_high`, `keyword_count_low` |
| `alias_resolve` | agent.py `_smart_search` | yes | `resolved_count`, `expansions_count` |
| `classify_mode` | classifier.py `classify_query_mode` (outer wrap) | yes | `mode`, `confidence`, `method` |
| `classify_mode_rules` | classifier.py `_rule_based_classify` | no (sync) | `mode`, `confidence` |
| `classify_mode_entity_check` | classifier.py `_check_entity_mentions` | yes | `candidate_count`, `matched` (bool) |
| `classify_mode_llm` | classifier.py `_llm_classify` | yes | `mode`, `confidence` |
| `embed_query` | agent.py `_smart_search` and `_search_knowledge` | yes | `text_count`, `total_chars` |
| `gather_searches` | agent.py `_smart_search` (wrap `asyncio.gather`) | yes | `mode`, `branch_count` |
| `search_es` | agent.py `_es_search_coro` body | yes | `result_count`, `top_k`, `source_type` |
| `search_graph` | agent.py `_graph_search_coro` body | yes | `result_len` (chars) |
| `search_entity_vdb` | agent.py `_entity_vdb_search_coro` body | yes | `result_count` |
| `search_rel_vdb` | agent.py `_rel_vdb_search_coro` body | yes | `result_count` |
| `fetch_user_context` | agent.py `_fetch_user_context` | yes | `memory_count`, `conversation_chars` |
| `assemble_context` | agent.py `_smart_search` (wrap `assemble_context`) | no (sync) | `total_tokens` |
| `llm_turn` | agent.py `answer()` / `answer_streaming()` Phase A loop | yes | `turn_idx`, `input_tokens`, `output_tokens`, `stop_reason` |
| `llm_stream_phase_b` | agent.py `answer_streaming()` Phase B | yes | `input_tokens`, `output_tokens` |
| `tool_execute` | agent.py `_execute_tool` dispatch | yes | `tool_name` |
| `hybrid_search_es_query` | hybrid_search.py `search()` (around `client.search`) | yes | `index`, `top_k`, `has_filters` |

**Field binding rules:**

- **Input-side fields** (known before the block: `top_k`, `query_len`, `tool_name`) — pass as `**fields` kwargs to `timed_step`. They appear in the `step_<name>` log line.
- **Output-side fields** (only known after the block: `result_count`, `keyword_count_high`, `mode`, `confidence`) — emit a separate `logger.info("<name>_result", ...)` call after the `async with` exits. Do not try to mutate the yielded span dict for these; the span dict carries `duration_ms` only.

Several call sites in `agent.py` already emit result-shape log lines today (e.g. `agent_tool_call`, `hybrid_search`). Keep those; do not duplicate. The instrumentation map's "Extra fields" column lists fields the developer should ensure are visible somewhere in the log stream for that step — either via `timed_step` kwargs or an existing/added result log line.

### Correlation

Already solved. `pam/common/logging.py` configures structlog with a `merge_contextvars` processor, and `pam/api/middleware.py` binds a per-request `correlation_id` into contextvars. Every `logger.info` in the request lifetime inherits it. No changes needed.

## Data Flow

Per request, the log stream (filtered to `step_*` events, sorted by timestamp) looks like:

```
step_keyword_extraction        duration_ms=1247.3  query_len=42
step_alias_resolve             duration_ms=87.1    resolved_count=1
step_classify_mode_rules       duration_ms=0.4     mode=hybrid confidence=0.4
step_classify_mode_entity_check duration_ms=124.6  candidate_count=2 matched=false
step_classify_mode_llm         duration_ms=1102.5  mode=conceptual confidence=0.85
step_classify_mode             duration_ms=1227.8  mode=conceptual method=llm
step_embed_query               duration_ms=312.4   text_count=2
step_search_es                 duration_ms=187.2   result_count=5
step_search_graph              duration_ms=612.0   result_len=2840
step_search_entity_vdb         duration_ms=92.1    result_count=5
step_search_rel_vdb            duration_ms=88.3    result_count=5
step_gather_searches           duration_ms=614.7   branch_count=4
step_fetch_user_context        duration_ms=204.8   memory_count=3
step_assemble_context          duration_ms=18.4    total_tokens=8120
step_llm_turn                  duration_ms=4821.3  turn_idx=0 input_tokens=2100 stop_reason=tool_use
step_tool_execute              duration_ms=8.2     tool_name=smart_search
step_llm_turn                  duration_ms=5102.8  turn_idx=1 input_tokens=10500 stop_reason=end_turn
step_total_answer              duration_ms=13_840  iterations=2 tool_calls=1
```

(Numbers above are illustrative, not measured.)

## Analysis Workflow

After deploy, the developer runs sample queries against `/chat/debug` and inspects logs:

```bash
# 1. Run a representative query (correlation_id returned in response headers / logs)
curl -s -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "what services depend on the authentication module?"}'

# 2. Pull all timing events for that correlation_id from the log file
grep '"correlation_id":"abc-123"' logs.jsonl \
  | jq -r 'select(.event | startswith("step_")) | "\(.duration_ms)ms\t\(.event)"' \
  | sort -rn
```

Repeat across 5–10 questions drawn from `eval/questions.json`. Build a hand table of per-step p50/p95. Decide remediation in a follow-up spec.

## Error Handling

`timed_step` and `timed_block` catch exceptions, log `step_<name>_failed` with `duration_ms` and `exc_info`, then re-raise. The agent's existing try/except blocks around tool calls and LLM calls continue to work unchanged — they just see exceptions propagate after one extra log line.

No swallowing. No fallback values. The instrumentation is observability, not control flow.

## Testing

**Unit** — `tests/common/test_timing.py`:

- `test_timed_step_logs_duration_on_success`: enter/exit, assert `step_X` event captured with `duration_ms > 0`.
- `test_timed_step_logs_failure_on_exception`: raise inside the block, assert `step_X_failed` captured and exception re-raised.
- `test_timed_step_yields_span_dict_with_duration_after_exit`: assert the yielded dict's `duration_ms` is updated after the block exits.
- `test_timed_block_sync_variant`: same three cases, sync version.
- `test_extra_fields_propagated`: pass `query_len=42`, assert it appears in the log event.

Use `structlog.testing.capture_logs()` to inspect emitted events.

**Integration** — existing agent tests must still pass unchanged. Add one new test:

- `test_answer_emits_step_events`: mock the Anthropic + search clients, call `agent.answer("test")`, capture logs, assert that `step_total_answer`, at least one `step_llm_turn`, and `step_tool_execute` all appear with `duration_ms > 0`.

**Manual** — run 5–10 questions from `eval/questions.json` against a local dev server with `LOG_LEVEL=INFO`. Grep logs for `step_*` events. Confirm every step listed in the instrumentation map appears at least once across the corpus, and that durations are non-zero and roughly match expected order-of-magnitude.

## Out of Scope

- Performance fixes — explicitly deferred to a follow-up spec written after timing data is in hand.
- Wrapping every single function in the agent — only the listed sites. Add more later if a hot path needs sub-step detail.
- Production aggregation — manual grep is enough for the first decision cycle.

## Open Questions

None at this point. Approve and proceed to implementation plan.
