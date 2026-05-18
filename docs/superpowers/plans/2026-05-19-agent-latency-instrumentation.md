# Agent Latency Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-step `time.perf_counter()` instrumentation across the retrieval agent so a single sample query produces a structured log trail showing exactly where wall-clock time is spent.

**Architecture:** A single new `src/pam/common/timing.py` module exposes `timed_step` (async ctxmanager) and `timed_block` (sync ctxmanager). Both emit `step_<name>` structlog events with `duration_ms`. Instrumentation is added inline at the call sites listed in the spec. Existing `correlation_id` contextvar wiring already ties all events together.

**Tech Stack:** Python 3.13, structlog (already configured), pytest + `structlog.testing.capture_logs`, `time.perf_counter`. No new third-party deps.

**Spec:** [docs/superpowers/specs/2026-05-19-agent-latency-instrumentation-design.md](../specs/2026-05-19-agent-latency-instrumentation-design.md)

---

## File Structure

**Create:**
- `src/pam/common/timing.py` — `timed_step` (async) + `timed_block` (sync) context managers.
- `tests/test_common/test_timing.py` — unit tests for both ctxmanagers.

**Modify:**
- `src/pam/agent/agent.py` — instrument `answer()`, `answer_streaming()`, `_smart_search()`, `_search_knowledge()`, `_fetch_user_context()`, `_execute_tool()`.
- `src/pam/agent/keyword_extractor.py` — instrument `extract_query_keywords()`.
- `src/pam/agent/query_classifier.py` — instrument `classify_query_mode()`, `_rule_based_classify()`, `_check_entity_mentions()`, `_llm_classify()`.
- `src/pam/retrieval/hybrid_search.py` — instrument `HybridSearchService.search()` ES query.
- `tests/test_agent/test_agent.py` — add `test_answer_emits_step_events` integration test.

---

## Task 1: Create timing module + unit tests

**Files:**
- Create: `src/pam/common/timing.py`
- Create: `tests/test_common/test_timing.py`

- [ ] **Step 1: Write failing test for `timed_step` success path**

Create `tests/test_common/test_timing.py`:

```python
"""Tests for pam.common.timing context managers."""

from __future__ import annotations

import asyncio

import pytest
import structlog
from structlog.testing import capture_logs

from pam.common.timing import timed_block, timed_step


@pytest.mark.asyncio
async def test_timed_step_logs_duration_on_success():
    logger = structlog.get_logger("test")
    with capture_logs() as logs:
        async with timed_step(logger, "demo"):
            await asyncio.sleep(0.01)

    events = [e for e in logs if e["event"] == "step_demo"]
    assert len(events) == 1
    assert events[0]["duration_ms"] > 0
    assert events[0]["log_level"] == "info"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_common/test_timing.py::test_timed_step_logs_duration_on_success -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.common.timing'`

- [ ] **Step 3: Implement timing module**

Create `src/pam/common/timing.py`:

```python
"""Lightweight async/sync context managers for step timing.

Both managers emit a structlog event named `step_<name>` on successful exit
and `step_<name>_failed` on exception. Each event carries `duration_ms`
(wall-clock milliseconds from enter to exit). Extra keyword arguments passed
to the context manager are merged into the event.

The `correlation_id` field is injected automatically by the global structlog
processor configured in `pam.common.logging`, so timing events from the same
request are easy to group.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import structlog


@asynccontextmanager
async def timed_step(
    logger: structlog.stdlib.BoundLogger,
    step: str,
    **fields: Any,
) -> AsyncIterator[dict[str, float]]:
    """Time an async block.

    Yields a single-key dict (`{"duration_ms": float}`) populated on exit so
    callers may read the measured duration after the `async with` ends.
    Re-raises any exception raised inside the block.
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
    """Synchronous twin of `timed_step` for sync code paths."""
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

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_common/test_timing.py::test_timed_step_logs_duration_on_success -v`
Expected: PASS.

- [ ] **Step 5: Add remaining unit tests**

Append to `tests/test_common/test_timing.py`:

```python
@pytest.mark.asyncio
async def test_timed_step_logs_failure_on_exception():
    logger = structlog.get_logger("test")
    with capture_logs() as logs:
        with pytest.raises(ValueError):
            async with timed_step(logger, "demo"):
                raise ValueError("boom")

    events = [e for e in logs if e["event"] == "step_demo_failed"]
    assert len(events) == 1
    assert events[0]["duration_ms"] > 0
    assert events[0]["log_level"] == "warning"


@pytest.mark.asyncio
async def test_timed_step_span_dict_populated_after_exit():
    logger = structlog.get_logger("test")
    async with timed_step(logger, "demo") as span:
        assert span["duration_ms"] == 0.0
        await asyncio.sleep(0.005)
    assert span["duration_ms"] > 0


@pytest.mark.asyncio
async def test_timed_step_extra_fields_propagated():
    logger = structlog.get_logger("test")
    with capture_logs() as logs:
        async with timed_step(logger, "demo", query_len=42, mode="hybrid"):
            pass

    events = [e for e in logs if e["event"] == "step_demo"]
    assert len(events) == 1
    assert events[0]["query_len"] == 42
    assert events[0]["mode"] == "hybrid"


def test_timed_block_logs_duration_on_success():
    logger = structlog.get_logger("test")
    with capture_logs() as logs:
        with timed_block(logger, "demo"):
            time.sleep(0.01)

    events = [e for e in logs if e["event"] == "step_demo"]
    assert len(events) == 1
    assert events[0]["duration_ms"] > 0


def test_timed_block_logs_failure_on_exception():
    logger = structlog.get_logger("test")
    with capture_logs() as logs, pytest.raises(RuntimeError):
        with timed_block(logger, "demo"):
            raise RuntimeError("boom")

    events = [e for e in logs if e["event"] == "step_demo_failed"]
    assert len(events) == 1


def test_timed_block_span_dict_populated_after_exit():
    logger = structlog.get_logger("test")
    with timed_block(logger, "demo") as span:
        assert span["duration_ms"] == 0.0
        time.sleep(0.005)
    assert span["duration_ms"] > 0
```

Also add `import time` at the top of the file (next to `import asyncio`).

- [ ] **Step 6: Run all timing tests**

Run: `pytest tests/test_common/test_timing.py -v`
Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add src/pam/common/timing.py tests/test_common/test_timing.py
git commit -m "feat(common): add timed_step / timed_block context managers

Lightweight async + sync structlog timing helpers for instrumenting
hot paths. Both emit step_<name> events with duration_ms on success
and step_<name>_failed on exception."
```

---

## Task 2: Instrument keyword extractor

**Files:**
- Modify: `src/pam/agent/keyword_extractor.py`

- [ ] **Step 1: Wrap the Anthropic call with `timed_step`**

In `src/pam/agent/keyword_extractor.py`, replace the body of `extract_query_keywords` (the `try:` block that currently calls `client.messages.create`) to wrap the network call in `timed_step` and emit a result-shape log line after exit.

Change:

```python
import json
from dataclasses import dataclass
from typing import cast

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import TextBlock
```

to add the timing import:

```python
import json
from dataclasses import dataclass
from typing import cast

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import TextBlock

from pam.common.timing import timed_step
```

Then replace the inside of `extract_query_keywords`:

```python
async def extract_query_keywords(
    client: AsyncAnthropic,
    query: str,
    model: str = "claude-3-5-haiku-20241022",
    timeout: float = 15.0,
) -> QueryKeywords:
    prompt = KEYWORD_EXTRACTION_PROMPT.format(query=query)

    try:
        async with timed_step(logger, "keyword_extraction", query_len=len(query), model=model):
            response = await client.messages.create(
                model=model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )
        raw_text = cast(TextBlock, response.content[0]).text.strip()
        data = json.loads(raw_text)
        result = QueryKeywords(
            high_level_keywords=data.get("high_level_keywords", []),
            low_level_keywords=data.get("low_level_keywords", []),
        )
        logger.info(
            "keyword_extraction_result",
            keyword_count_high=len(result.high_level_keywords),
            keyword_count_low=len(result.low_level_keywords),
        )
        return result
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.warning("keyword_extraction_parse_failed", query=query[:100])
        raise
    except Exception:
        logger.warning("keyword_extraction_failed", query=query[:100], exc_info=True)
        raise
```

The `async with timed_step(...)` is scoped to the network call only so JSON parsing errors don't pollute the `keyword_extraction` timing. Result counts go in a separate `keyword_extraction_result` event after the parse succeeds.

- [ ] **Step 2: Run existing keyword extractor tests**

Run: `pytest tests/test_agent -k keyword -v`
Expected: existing tests still pass (or "no tests collected" if none exist — that's also OK).

- [ ] **Step 3: Commit**

```bash
git add src/pam/agent/keyword_extractor.py
git commit -m "feat(agent): instrument keyword_extraction with timed_step

Wraps the Haiku call in timed_step and emits a separate result log
line carrying high/low keyword counts."
```

---

## Task 3: Instrument query classifier

**Files:**
- Modify: `src/pam/agent/query_classifier.py`

- [ ] **Step 1: Add timing import**

In `src/pam/agent/query_classifier.py`, add the timing import next to existing imports:

```python
from pam.common.timing import timed_block, timed_step
```

- [ ] **Step 2: Wrap `_rule_based_classify` with `timed_block`**

`_rule_based_classify` is sync and very fast (sub-millisecond). Wrap its entire body with `timed_block` so we still get a `step_classify_mode_rules` event:

```python
def _rule_based_classify(query: str, settings: Settings) -> ClassificationResult:
    """Classify a query using rule-based heuristics.

    Priority order (highest specificity first):
    1. Temporal (time-related keywords)
    2. Factual (question patterns, with negative signal for entity/conceptual overlap)
    3. Conceptual (relationship keywords)
    4. Hybrid fallback (no confident match)
    """
    with timed_block(logger, "classify_mode_rules", query_len=len(query)):
        query_lower = query.lower().strip()

        # Parse keyword lists from settings
        temporal_keywords = [kw.strip() for kw in settings.mode_temporal_keywords.split(",")]
        factual_patterns = [pat.strip() for pat in settings.mode_factual_patterns.split(",")]
        conceptual_keywords = [kw.strip() for kw in settings.mode_conceptual_keywords.split(",")]

        # Build regex patterns with word boundaries
        temporal_regexes = [re.compile(rf"\b{re.escape(kw)}\b") for kw in temporal_keywords]
        factual_regexes = [re.compile(rf"^{re.escape(pat)}\b") for pat in factual_patterns]
        conceptual_regexes = [re.compile(rf"\b{re.escape(kw)}\b") for kw in conceptual_keywords]

        # 1. Temporal (highest specificity)
        temporal_matches = sum(1 for rx in temporal_regexes if rx.search(query_lower))
        if temporal_matches >= 2:
            return ClassificationResult(RetrievalMode.TEMPORAL, 0.9, "rules")
        if temporal_matches == 1:
            return ClassificationResult(RetrievalMode.TEMPORAL, 0.75, "rules")

        # 2. Factual (question patterns, anchored to start)
        factual_match = any(rx.search(query_lower) for rx in factual_regexes)
        if factual_match:
            conceptual_overlap = any(rx.search(query_lower) for rx in conceptual_regexes)
            has_entity_mention = bool(_MULTI_WORD_CAP_RE.search(query)) or bool(_PASCAL_CASE_RE.search(query))
            if conceptual_overlap or has_entity_mention:
                return ClassificationResult(RetrievalMode.FACTUAL, 0.5, "rules")
            return ClassificationResult(RetrievalMode.FACTUAL, 0.8, "rules")

        # 3. Conceptual (relationship keywords)
        conceptual_matches = sum(1 for rx in conceptual_regexes if rx.search(query_lower))
        if conceptual_matches >= 2:
            return ClassificationResult(RetrievalMode.CONCEPTUAL, 0.85, "rules")
        if conceptual_matches == 1:
            return ClassificationResult(RetrievalMode.CONCEPTUAL, 0.7, "rules")

        # 4. No confident match
        return ClassificationResult(RetrievalMode.HYBRID, 0.4, "rules")
```

- [ ] **Step 3: Wrap `_check_entity_mentions` with `timed_step`**

In `_check_entity_mentions`, wrap the entire async body. Read the current function first to see the existing structure, then wrap everything inside the function body (after the docstring) in `async with timed_step(logger, "classify_mode_entity_check", query_len=len(query)):`. Keep the existing `return None` / `return ClassificationResult(...)` lines inside the block. The early `return None` when `candidates` is empty stays inside the block too.

- [ ] **Step 4: Wrap `_llm_classify` with `timed_step`**

Find `_llm_classify` in `src/pam/agent/query_classifier.py` and wrap the Anthropic call (`await client.messages.create(...)`) with `async with timed_step(logger, "classify_mode_llm", query_len=len(query)):`. Place the JSON parsing OUTSIDE the timed block so parse time isn't counted as LLM time. The outer try/except for parse failures stays unchanged.

- [ ] **Step 5: Wrap outer `classify_query_mode` with `timed_step`**

In `classify_query_mode`, wrap the entire body (from `settings = get_settings()` through the final `return result`) in:

```python
async with timed_step(logger, "classify_mode", query_len=len(query)) as span:
    settings = get_settings()
    threshold = settings.mode_confidence_threshold
    # ... existing body ...
    return result
```

The existing `logger.info("query_mode_classified", ...)` calls already carry `mode`, `confidence`, `method` — keep them. They serve as the result-shape log for `classify_mode`.

- [ ] **Step 6: Run classifier tests**

Run: `pytest tests/test_agent -k classif -v`
Expected: existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/pam/agent/query_classifier.py
git commit -m "feat(agent): instrument query classifier tiers

Adds step_classify_mode (outer), step_classify_mode_rules,
step_classify_mode_entity_check, step_classify_mode_llm timing
events so each tier of the two-tier classifier is measurable
independently."
```

---

## Task 4: Instrument hybrid_search ES call

**Files:**
- Modify: `src/pam/retrieval/hybrid_search.py`

- [ ] **Step 1: Add timing import**

Add to the imports in `src/pam/retrieval/hybrid_search.py`:

```python
from pam.common.timing import timed_step
```

- [ ] **Step 2: Wrap the `client.search` call**

In `HybridSearchService.search`, find the `try:` block that wraps `response = await self.client.search(...)`. Wrap just that one network call in `timed_step`:

```python
try:
    async with timed_step(
        logger,
        "hybrid_search_es_query",
        index=self.index_name,
        top_k=top_k,
        has_filters=bool(filters),
    ):
        response = await self.client.search(index=self.index_name, body=body)
except Exception as exc:
    logger.exception(
        "hybrid_search_es_error",
        query_length=len(query),
        top_k=top_k,
        source_type=source_type,
        project=project,
    )
    raise SearchBackendError(f"Elasticsearch search failed: {exc}") from exc
```

The existing `logger.info("hybrid_search", ...)` near the end of the function already carries `results=len(results)` — keep it as the result-shape log line.

- [ ] **Step 3: Run retrieval tests**

Run: `pytest tests/test_retrieval -v`
Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/pam/retrieval/hybrid_search.py
git commit -m "feat(retrieval): instrument hybrid search ES query

Wraps the client.search call in timed_step so the ES round-trip
shows up as step_hybrid_search_es_query with duration_ms,
separate from result-shaping work."
```

---

## Task 5: Instrument agent `_fetch_user_context`

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Add timing import**

Add to imports in `src/pam/agent/agent.py`:

```python
from pam.common.timing import timed_block, timed_step
```

- [ ] **Step 2: Wrap `_fetch_user_context` body**

In `src/pam/agent/agent.py`, find `_fetch_user_context`. Wrap its entire body inside `async with timed_step(logger, "fetch_user_context", has_memory=self._memory_service is not None, has_conv=self._conversation_service is not None):`. After the block, log a result event with `memory_count` and `conversation_chars`:

```python
async def _fetch_user_context(self, query: str) -> tuple[list[dict], str]:
    """Fetch user memories + recent conversation context for the current request.

    Returns ``(memory_results, conversation_context)``. Both tools
    (smart_search and search_knowledge) call this so per-user memory and
    conversation state are injected regardless of which tool the LLM picks.
    Returns empty results when the services or per-request IDs aren't set.
    """
    memory_results: list[dict] = []
    conversation_context = ""

    async with timed_step(
        logger,
        "fetch_user_context",
        has_memory=self._memory_service is not None,
        has_conv=self._conversation_service is not None,
    ):
        if self._memory_service and self._current_user_id:
            try:
                raw_memories = await self._memory_service.search(
                    query=query,
                    user_id=self._current_user_id,
                    top_k=5,
                )
                memory_results = [
                    {"content": m.memory.content, "type": m.memory.type, "score": m.score} for m in raw_memories
                ]
            except Exception:
                logger.warning("user_context_memory_failed", exc_info=True)

        if self._conversation_service and self._current_conversation_id:
            try:
                settings = get_settings()
                conversation_context = await self._conversation_service.get_recent_context(
                    self._current_conversation_id,
                    max_tokens=settings.conversation_context_max_tokens,
                )
            except Exception:
                logger.warning("user_context_conversation_failed", exc_info=True)

    logger.info(
        "fetch_user_context_result",
        memory_count=len(memory_results),
        conversation_chars=len(conversation_context),
    )
    return memory_results, conversation_context
```

- [ ] **Step 3: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument _fetch_user_context

Memory + recent conversation lookup now emits step_fetch_user_context
with duration_ms, plus a result log line with memory_count and
conversation_chars."
```

---

## Task 6: Instrument agent `_smart_search` — pre-search chain

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Wrap alias resolution**

In `src/pam/agent/agent.py` `_smart_search`, locate the "Step A1: Resolve glossary aliases" block. Wrap the resolver call with `timed_step`:

```python
# Step A1: Resolve glossary aliases
from pam.common.models import ResolvedTermItem

resolved_terms: list[ResolvedTermItem] = []
if self._alias_resolver is not None:
    try:
        async with timed_step(logger, "alias_resolve", query_len=len(query)):
            resolved = await self._alias_resolver.resolve(query)
        if resolved.resolved_terms:
            resolved_terms = resolved.resolved_terms
            # Enhance ES query with canonical terms for better BM25 recall
            expansions = [rt.canonical for rt in resolved_terms if rt.matched.lower() != rt.canonical.lower()]
            if expansions:
                query = f"{query} {' '.join(expansions)}"
                logger.info("smart_search_query_expanded", expansions=expansions)
    except Exception:
        logger.warning("smart_search_alias_resolution_failed", exc_info=True)

logger.info(
    "alias_resolve_result",
    resolved_count=len(resolved_terms),
)
```

The keyword extractor call (already done in Task 2) emits its own `step_keyword_extraction` event from inside that function, so no extra wrapping at the `_smart_search` call site is needed.

- [ ] **Step 2: Wrap embedding call**

In `_smart_search`, find "Step B2: Embed both queries upfront" (the `query_embeddings = await self.embedder.embed_texts([es_query, graph_query])` line). Wrap it:

```python
# Step B2: Embed both queries upfront (reuse for VDB searches)
async with timed_step(
    logger,
    "embed_query",
    text_count=2,
    total_chars=len(es_query) + len(graph_query),
):
    query_embeddings = await self.embedder.embed_texts([es_query, graph_query])
es_query_embedding = query_embeddings[0]
graph_query_embedding = query_embeddings[1]
```

- [ ] **Step 3: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument smart_search pre-search chain

Adds step_alias_resolve and step_embed_query timing events so the
glossary resolver and OpenAI embedding call can be measured
independently of downstream search backends."
```

---

## Task 7: Instrument agent `_smart_search` — concurrent search branches

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Wrap each search coroutine body with `timed_step`**

In `_smart_search`, replace the four `_*_coro` definitions to wrap their bodies:

```python
# Step C: Define async search coroutines
async def _es_search_coro() -> list:
    async with timed_step(
        logger,
        "search_es",
        top_k=es_limit,
        source_type=self._default_source_type,
    ):
        results = await self.search.search(
            query=es_query,
            query_embedding=es_query_embedding,
            top_k=es_limit,
            source_type=self._default_source_type,
        )
    logger.info("search_es_result", result_count=len(results))
    return results

async def _graph_search_coro() -> str:
    if self.graph_service is None:
        return ""
    from pam.graph.query import search_graph_relationships

    async with timed_step(logger, "search_graph", query_len=len(graph_query)):
        result = await search_graph_relationships(
            graph_service=self.graph_service,
            query=graph_query,
        )
    logger.info("search_graph_result", result_len=len(result))
    return result

async def _entity_vdb_search_coro() -> list[dict]:
    if self.vdb_store is None:
        return []
    async with timed_step(
        logger,
        "search_entity_vdb",
        top_k=settings.smart_search_entity_limit,
    ):
        results = await self.vdb_store.search_entities(
            query_embedding=es_query_embedding,
            top_k=settings.smart_search_entity_limit,
        )
    logger.info("search_entity_vdb_result", result_count=len(results))
    return results

async def _rel_vdb_search_coro() -> list[dict]:
    if self.vdb_store is None:
        return []
    async with timed_step(
        logger,
        "search_rel_vdb",
        top_k=settings.smart_search_relationship_limit,
    ):
        results = await self.vdb_store.search_relationships(
            query_embedding=graph_query_embedding,
            top_k=settings.smart_search_relationship_limit,
        )
    logger.info("search_rel_vdb_result", result_count=len(results))
    return results
```

- [ ] **Step 2: Wrap the `asyncio.gather` call**

In `_smart_search`, locate the `asyncio.gather(es_coro, graph_coro, entity_vdb_coro, rel_vdb_coro, return_exceptions=True)` call. Wrap it:

```python
# Step D: Run searches concurrently (mode-conditioned)
# ... mode-based coro selection unchanged ...

async with timed_step(logger, "gather_searches", mode=mode.value, branch_count=4):
    es_result, graph_result, entity_vdb_result, rel_vdb_result = await asyncio.gather(
        es_coro,
        graph_coro,
        entity_vdb_coro,
        rel_vdb_coro,
        return_exceptions=True,
    )
```

- [ ] **Step 3: Wrap `assemble_context` with `timed_block`**

The `assemble_context` call in `_smart_search` is synchronous. Wrap it:

```python
# Step F: Assemble structured context with token budgets
# ... budget construction unchanged ...

with timed_block(logger, "assemble_context"):
    assembled = assemble_context(
        es_results=es_results,
        graph_text=graph_text,
        entity_vdb_results=entity_vdb_results,
        rel_vdb_results=rel_vdb_results,
        budget=budget,
        memory_results=memory_results,
        conversation_context=conversation_context,
        glossary_results=glossary_context if glossary_context else None,
    )

logger.info("assemble_context_result", total_tokens=assembled.total_tokens)
```

If `assembled.total_tokens` is not the correct attribute name, inspect `src/pam/agent/context_assembly.py` for the actual field on the assembled object and use that. If no such field exists, drop the `total_tokens=` kwarg from the result log line (keep the event itself).

- [ ] **Step 4: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument smart_search concurrent retrieval

Each of the four search branches (ES, graph, entity VDB, relationship
VDB) and the outer gather + sync context assembly now emit timing
events. Per-branch step_search_* lines expose which backend is the
gather bottleneck."
```

---

## Task 8: Instrument agent `_search_knowledge`

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Wrap embedding + search**

In `src/pam/agent/agent.py` `_search_knowledge`, wrap the embedding call and the `self.search.search(...)` call:

```python
async def _search_knowledge(self, input_: dict) -> tuple[str, list[Citation]]:
    """Execute the search_knowledge tool."""
    query = input_["query"]
    source_type = input_.get("source_type") or self._default_source_type

    memory_results, conversation_context = await self._fetch_user_context(query)

    async with timed_step(logger, "embed_query", text_count=1, total_chars=len(query)):
        query_embeddings = await self.embedder.embed_texts([query])
    query_embedding = query_embeddings[0]

    try:
        async with timed_step(logger, "search_es", top_k=10, source_type=source_type):
            results = await self.search.search(
                query=query,
                query_embedding=query_embedding,
                top_k=10,
                source_type=source_type,
            )
        logger.info("search_es_result", result_count=len(results))
    except SearchBackendError as exc:
        logger.warning("search_backend_error", query=query[:100], error=str(exc))
        return "Search is temporarily unavailable. Please try again.", []

    # ... rest of function unchanged ...
```

Keep everything after the `try/except` block (citations, formatting, sections assembly) untouched.

- [ ] **Step 2: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 3: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument search_knowledge tool path

Adds step_embed_query and step_search_es timing events to the
search_knowledge tool so the alternate (non-smart_search) retrieval
path is measurable too."
```

---

## Task 9: Instrument agent `_execute_tool` dispatcher

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Wrap dispatcher body**

Replace the body of `_execute_tool`:

```python
async def _execute_tool(self, tool_name: str, tool_input: dict) -> tuple[str, list[Citation]]:
    """Execute a tool call and return (result_text, citations)."""
    async with timed_step(logger, "tool_execute", tool_name=tool_name):
        if tool_name == "smart_search":
            return await self._smart_search(tool_input)
        if tool_name == "search_knowledge":
            return await self._search_knowledge(tool_input)
        if tool_name == "get_document_context":
            return await self._get_document_context(tool_input)
        if tool_name == "get_change_history":
            return await self._get_change_history(tool_input)
        if tool_name == "query_database":
            return await self._query_database(tool_input)
        if tool_name == "search_entities":
            return await self._search_entities(tool_input)
        if tool_name == "search_knowledge_graph":
            return await self._search_knowledge_graph(tool_input)
        if tool_name == "get_entity_history":
            return await self._get_entity_history(tool_input)
        return f"Unknown tool: {tool_name}", []
```

The wrapping `async with timed_step` covers all early returns — `timed_step` logs duration on whichever return path fires.

- [ ] **Step 2: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 3: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument _execute_tool dispatcher

Single step_tool_execute event per tool call carries tool_name and
duration_ms so total tool dispatch overhead is visible distinct
from the underlying retrieval work."
```

---

## Task 10: Instrument LLM turns in `answer()`

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Wrap each LLM call inside the tool-use loop**

In `answer()`, replace the `for _ in range(MAX_TOOL_ITERATIONS):` loop body so each `self.client.messages.create(...)` is wrapped:

```python
for turn_idx in range(MAX_TOOL_ITERATIONS):
    async with timed_step(logger, "llm_turn", turn_idx=turn_idx) as span:
        call_start = time.perf_counter()
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=cast(Any, messages),
            tools=cast(Any, ALL_TOOLS),
        )
        call_latency = (time.perf_counter() - call_start) * 1000

    total_input_tokens += response.usage.input_tokens
    total_output_tokens += response.usage.output_tokens
    self.cost_tracker.log_llm_call(
        self.model, response.usage.input_tokens, response.usage.output_tokens, call_latency
    )
    logger.info(
        "llm_turn_result",
        turn_idx=turn_idx,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=response.stop_reason,
        duration_ms=span["duration_ms"],
    )

    # ... rest of loop body (stop_reason checks, tool execution) unchanged ...
```

Replace the existing `for _ in range(...)` with `for turn_idx in range(...)`. Keep the existing `call_start`/`call_latency` math intact — the cost tracker still uses it. The `timed_step` wraps only the network call, not the post-processing.

- [ ] **Step 2: Wrap the entire `answer()` body with `step_total_answer`**

Wrap the body of `answer()` (after `self._default_source_type = source_type` and `start = time.perf_counter()`) in an outer `timed_step`. The inner `return AgentResponse(...)` calls need to become `result = AgentResponse(...)` + `break` so the outer `async with` exits cleanly. Apply this restructuring:

```python
async def answer(
    self,
    question: str,
    conversation_history: list | None = None,
    source_type: str | None = None,
) -> AgentResponse:
    self._default_source_type = source_type
    start = time.perf_counter()

    result: AgentResponse | None = None
    turn_idx = 0

    async with timed_step(
        logger,
        "total_answer",
        streaming=False,
        question_len=len(question),
    ):
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": question})
        messages = _truncate_history(messages)

        all_citations: list[Citation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        all_retrieved_context: list[str] = []

        for turn_idx in range(MAX_TOOL_ITERATIONS):
            async with timed_step(logger, "llm_turn", turn_idx=turn_idx) as span:
                call_start = time.perf_counter()
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=cast(Any, messages),
                    tools=cast(Any, ALL_TOOLS),
                )
                call_latency = (time.perf_counter() - call_start) * 1000

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            self.cost_tracker.log_llm_call(
                self.model, response.usage.input_tokens, response.usage.output_tokens, call_latency
            )
            logger.info(
                "llm_turn_result",
                turn_idx=turn_idx,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                stop_reason=response.stop_reason,
                duration_ms=span["duration_ms"],
            )

            if response.stop_reason == "end_turn":
                answer_text = self._extract_text(response.content)
                total_latency = (time.perf_counter() - start) * 1000
                result = AgentResponse(
                    answer=answer_text,
                    citations=all_citations,
                    token_usage={
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                    },
                    latency_ms=round(total_latency, 1),
                    tool_calls=tool_call_count,
                    retrieval_mode=self._last_classification.mode.value if self._last_classification else None,
                    mode_confidence=self._last_classification.confidence if self._last_classification else None,
                    retrieved_context=all_retrieved_context,
                )
                break

            if response.stop_reason != "tool_use":
                logger.warning("unexpected_stop_reason", stop_reason=response.stop_reason)
                answer_text = self._extract_text(response.content)
                total_latency = (time.perf_counter() - start) * 1000
                result = AgentResponse(
                    answer=answer_text or "The response was cut short. Please try a more specific question.",
                    citations=all_citations,
                    token_usage={
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                    },
                    latency_ms=round(total_latency, 1),
                    tool_calls=tool_call_count,
                    retrieval_mode=self._last_classification.mode.value if self._last_classification else None,
                    mode_confidence=self._last_classification.confidence if self._last_classification else None,
                    retrieved_context=all_retrieved_context,
                )
                break

            # tool_use branch
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_call_count += 1
                    res, citations = await self._execute_tool(block.name, block.input)
                    if block.name in ("search_knowledge", "smart_search") and isinstance(res, str):
                        all_retrieved_context.append(res)
                    all_citations.extend(citations)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": res,
                    })
                    logger.info(
                        "agent_tool_call",
                        tool=block.name,
                        input=block.input,
                        result_length=len(res),
                    )
            messages.append({"role": "user", "content": tool_results})
        else:
            total_latency = (time.perf_counter() - start) * 1000
            result = AgentResponse(
                answer=(
                    "I was unable to fully answer your question within the allowed number of search steps. "
                    "Please try rephrasing or asking a more specific question."
                ),
                citations=all_citations,
                token_usage={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
                latency_ms=round(total_latency, 1),
                tool_calls=tool_call_count,
                retrieval_mode=self._last_classification.mode.value if self._last_classification else None,
                mode_confidence=self._last_classification.confidence if self._last_classification else None,
                retrieved_context=all_retrieved_context,
            )

    logger.info(
        "total_answer_result",
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        tool_calls=tool_call_count,
        iterations=turn_idx + 1,
    )
    assert result is not None
    return result
```

Structural changes worth calling out: (a) inner `return AgentResponse(...)` becomes assign-to-`result` + `break` so the outer `async with` exits cleanly, (b) the trailing "hit max iterations" fallback is moved into the `for/else` clause for the same reason, (c) `turn_idx` is declared at function scope (`turn_idx = 0`) so the post-`async with` log line can read it without a `NameError` when the loop ran zero times (defensive — won't happen in practice given `MAX_TOOL_ITERATIONS=5`).

- [ ] **Step 3: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument LLM turns + total_answer in answer()

Each Claude tool-use turn emits step_llm_turn with turn_idx and
post-call token counts. Outer step_total_answer covers the full
answer() body. Restructured the loop to assign-to-result + break
so a single async with wraps all return paths."
```

---

## Task 11: Instrument `answer_streaming()`

**Files:**
- Modify: `src/pam/agent/agent.py`

- [ ] **Step 1: Wrap LLM turns in Phase A**

In `answer_streaming()` Phase A, wrap each non-streaming `messages.create` call:

```python
for turn_idx in range(MAX_TOOL_ITERATIONS):
    yield {"type": "status", "content": "Thinking..."}

    async with timed_step(logger, "llm_turn", turn_idx=turn_idx, streaming=True) as span:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=cast(Any, messages),
            tools=cast(Any, ALL_TOOLS),
        )
    total_input_tokens += response.usage.input_tokens
    total_output_tokens += response.usage.output_tokens
    logger.info(
        "llm_turn_result",
        turn_idx=turn_idx,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=response.stop_reason,
        duration_ms=span["duration_ms"],
    )

    # ... rest of Phase A loop body unchanged ...
```

Replace `for _ in range(...)` with `for turn_idx in range(...)`.

- [ ] **Step 2: Wrap Phase B streaming call**

Wrap the Phase B `async with self.client.messages.stream(...)` block:

```python
if tool_call_count > 0 and not answer_already_emitted:
    yield {"type": "status", "content": "Generating answer..."}
    async with timed_step(logger, "llm_stream_phase_b") as span:
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=cast(Any, messages),
            tools=cast(Any, ALL_TOOLS),
        ) as stream:
            async for text in stream.text_stream:
                yield {"type": "token", "content": text}
            final_message = await stream.get_final_message()
            total_input_tokens += final_message.usage.input_tokens
            total_output_tokens += final_message.usage.output_tokens
    logger.info(
        "llm_stream_phase_b_result",
        input_tokens=final_message.usage.input_tokens,
        output_tokens=final_message.usage.output_tokens,
        duration_ms=span["duration_ms"],
    )
```

- [ ] **Step 3: Wrap whole `answer_streaming` body with `step_total_answer`**

Wrap from just after `messages = _truncate_history(messages)` through the end of the `try:` block:

```python
async def answer_streaming(self, question, conversation_history=None, source_type=None):
    self._default_source_type = source_type
    start = time.perf_counter()
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": question})
    messages = _truncate_history(messages)

    all_citations: list[Citation] = []
    total_input_tokens = 0
    total_output_tokens = 0
    tool_call_count = 0
    answer_already_emitted = False

    async with timed_step(
        logger,
        "total_answer",
        streaming=True,
        question_len=len(question),
    ):
        try:
            # ... entire existing Phase A + Phase B + Phase C body unchanged
            #     except for the LLM turn / Phase B wrapping from Steps 1-2 ...
        except Exception as e:
            logger.exception("streaming_error", error=str(e))
            yield {
                "type": "error",
                "data": {"type": type(e).__name__, "message": str(e)},
                "message": f"An error occurred: {e!s}",
            }

    logger.info(
        "total_answer_result",
        streaming=True,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        tool_calls=tool_call_count,
    )
```

The `except` clause stays inside the `async with timed_step`. Exceptions caught inside the generator do not propagate out of `timed_step` (we caught them), so the helper logs `step_total_answer` (success) — desired, because the agent emitted a graceful error event to the SSE stream rather than crashing.

- [ ] **Step 4: Run agent tests**

Run: `pytest tests/test_agent -v`
Expected: existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/pam/agent/agent.py
git commit -m "feat(agent): instrument answer_streaming Phase A/B + total

Phase A LLM turns and Phase B streaming call now emit timing events
with streaming=true flag. Outer step_total_answer covers the entire
generator body so total streaming-path latency is measurable."
```

---

## Task 12: Integration test — agent emits step events

**Files:**
- Modify: `tests/test_agent/test_agent.py`

- [ ] **Step 1: Read current test file to see existing fixture style**

Run: `head -100 tests/test_agent/test_agent.py`
Expected: shows existing imports, fixtures, and existing tests using mocks for the Anthropic client. The new test reuses whichever fixture pattern is already in place.

- [ ] **Step 2: Write the integration test**

Append to `tests/test_agent/test_agent.py`. If `structlog` / `capture_logs` are not already imported at the top of the file, add them:

```python
import structlog  # noqa: F401  -- already may be present; merge with existing
from structlog.testing import capture_logs
```

Then add the test. Replace `<agent-fixture-name>` below with the actual fixture name used in this file (e.g. `agent`, `agent_with_mocks`, `retrieval_agent` — pick the one the other tests use). If no fixture exists, mirror the construction pattern from the closest existing test that calls `agent.answer(...)`:

```python
@pytest.mark.asyncio
async def test_answer_emits_step_events(<agent-fixture-name>):
    """Agent.answer() emits step_total_answer, step_llm_turn, step_tool_execute."""
    with capture_logs() as logs:
        await <agent-fixture-name>.answer("test question")

    step_events = [e for e in logs if e["event"].startswith("step_")]
    event_names = {e["event"] for e in step_events}

    assert "step_total_answer" in event_names
    assert "step_llm_turn" in event_names
    assert "step_tool_execute" in event_names

    for e in step_events:
        assert e["duration_ms"] >= 0
```

The mocked Anthropic client must return responses whose `stop_reason` chain triggers at least one tool call (`tool_use` then `end_turn`). Look at existing tests in the same file for the canned response shape and reuse it.

- [ ] **Step 3: Run the new test**

Run: `pytest tests/test_agent/test_agent.py::test_answer_emits_step_events -v`
Expected: PASS.

- [ ] **Step 4: Run the full agent test suite**

Run: `pytest tests/test_agent -v`
Expected: all tests pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent/test_agent.py
git commit -m "test(agent): verify answer() emits step events

Integration test asserts step_total_answer, step_llm_turn, and
step_tool_execute appear with non-negative duration_ms during a
normal agent.answer() call."
```

---

## Task 13: Manual smoke + final verification

**Files:** None (manual run only).

- [ ] **Step 1: Run the full test suite**

Run: `pytest -x`
Expected: all pass.

- [ ] **Step 2: Boot the dev server and hit `/chat`**

Terminal A:

```bash
docker compose up -d
uvicorn pam.api.main:app --reload --log-level info 2>&1 | tee /tmp/pam-latency.log
```

Terminal B:

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "what services depend on the authentication module?"}' \
  -o /tmp/response.json
cat /tmp/response.json | jq .
```

Expected: a normal `/chat` response with `latency_ms`, citations, and text answer.

- [ ] **Step 3: Inspect the log stream**

Run:

```bash
grep '"event":"step_' /tmp/pam-latency.log \
  | jq -r '"\(.duration_ms)ms\t\(.event)\t\(.correlation_id)"' \
  | sort
```

Expected: At least these events appear, all sharing the same `correlation_id`:

- `step_total_answer`
- `step_llm_turn` (at least once, likely twice)
- `step_tool_execute`
- `step_keyword_extraction` (if the LLM picked `smart_search`)
- `step_alias_resolve`
- `step_classify_mode`
- `step_classify_mode_rules`
- `step_embed_query`
- `step_search_es` (and/or other search branches depending on retrieval mode)
- `step_gather_searches`
- `step_fetch_user_context`
- `step_assemble_context`
- `step_hybrid_search_es_query`

All `duration_ms` values should be positive and order-of-magnitude sensible (sub-ms for regex classifier, ~hundreds of ms for embeddings/Haiku, seconds for the main LLM turns).

- [ ] **Step 4: Repeat with 4–5 more questions from `eval/questions.json`**

Run varied questions (one factual, one conceptual, one temporal if available). Confirm the matrix of step events varies by retrieval mode and no step is silently missing on its expected path.

- [ ] **Step 5: Build the per-step latency table**

For each query's correlation_id, sum `duration_ms` per step name, then average across queries. Save to a scratch file or share in chat — this is the artifact the follow-up optimization spec will be written from.

- [ ] **Step 6: Final commit (only if manual smoke surfaced issues)**

If the manual run surfaced a small fix (typo in a step name, missing field), apply it and commit:

```bash
git add -p
git commit -m "fix(agent): minor instrumentation cleanup post-smoke"
```

If nothing needed fixing, skip.

---

## Self-Review Notes

**Spec coverage:**

| Spec row | Task |
|----------|------|
| `total_answer` | 10 (answer), 11 (answer_streaming) |
| `keyword_extraction` | 2 |
| `alias_resolve` | 6 |
| `classify_mode` (outer) | 3 |
| `classify_mode_rules` | 3 |
| `classify_mode_entity_check` | 3 |
| `classify_mode_llm` | 3 |
| `embed_query` | 6 (smart_search), 8 (search_knowledge) |
| `gather_searches` | 7 |
| `search_es` | 7 (smart_search), 8 (search_knowledge) |
| `search_graph` | 7 |
| `search_entity_vdb` | 7 |
| `search_rel_vdb` | 7 |
| `fetch_user_context` | 5 |
| `assemble_context` | 7 |
| `llm_turn` | 10, 11 |
| `llm_stream_phase_b` | 11 |
| `tool_execute` | 9 |
| `hybrid_search_es_query` | 4 |

All instrumentation-map rows covered. Unit tests = Task 1; integration test = Task 12; manual smoke = Task 13.

**Placeholder scan:** No "TBD" / "implement later" / un-fleshed-out steps. Every code-changing step contains the actual code block. The one parametric placeholder (`<agent-fixture-name>` in Task 12) is explicitly called out and instructs the implementer how to resolve it from the existing test file.

**Type consistency:** `timed_step` and `timed_block` signatures stable across every use site. `span["duration_ms"]` is read only after the `async with`/`with` block exits. Step-name strings used in tests (`step_demo`, `step_demo_failed`) match the helper's `f"step_{step}"` / `f"step_{step}_failed"` formatting. Result log lines follow a consistent `<step>_result` naming convention.
