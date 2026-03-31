# PAM Context Benchmarking Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade PAM's evaluation from a basic 10-question keyword-overlap check to a production-grade benchmarking suite with standardized RAG metrics, faithfulness evaluation, latency percentiles, load testing, synthetic dataset generation, and CI gating.

**Architecture:** Extend the existing `eval/` module with DeepEval integration for standardized metrics, a new `/api/search-with-context` endpoint to expose retrieved context for faithfulness scoring, a synthetic question generator that reads ingested documents, and a locust-based load test. Wire the offline eval into CI as a quality gate.

**Tech Stack:** DeepEval (pytest-compatible RAG metrics), locust (load testing), existing Anthropic SDK (LLM judge), httpx (API client), statistics stdlib (percentiles)

---

## File Structure

```
eval/
├── __init__.py                    # existing
├── questions.json                 # existing — expand from 10 → 50+
├── judges.py                      # existing — add faithfulness metric
├── run_eval.py                    # existing — add percentiles, context capture
├── metrics.py                     # NEW — percentile stats, metric aggregation
├── synthetic_gen.py               # NEW — generate Q&A pairs from ingested docs
├── conftest.py                    # NEW — pytest fixtures for DeepEval integration
├── test_rag_quality.py            # NEW — DeepEval pytest test cases
├── load_test.py                   # NEW — locust load test for /api/search + /api/chat
└── datasets/
    └── synthetic_questions.json   # NEW — auto-generated evaluation dataset
src/pam/api/routes/
├── search.py                      # MODIFY — add /search-with-context endpoint
```

---

### Task 1: Add Latency Percentile Statistics

**Files:**
- Create: `eval/metrics.py`
- Modify: `eval/run_eval.py`

- [ ] **Step 1: Write the failing test for percentile calculation**

Create `tests/eval/test_metrics.py`:

```python
import pytest
from eval.metrics import compute_percentiles


def test_compute_percentiles_basic():
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    result = compute_percentiles(latencies)
    assert result["p50"] == pytest.approx(55.0, abs=1.0)
    assert result["p90"] == pytest.approx(95.0, abs=1.0)
    assert result["p99"] == pytest.approx(100.0, abs=1.0)
    assert result["min"] == 10.0
    assert result["max"] == 100.0
    assert result["mean"] == pytest.approx(55.0, abs=0.1)


def test_compute_percentiles_single_value():
    result = compute_percentiles([42.0])
    assert result["p50"] == 42.0
    assert result["p90"] == 42.0
    assert result["p99"] == 42.0


def test_compute_percentiles_empty():
    result = compute_percentiles([])
    assert result["p50"] == 0.0
    assert result["mean"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/eval/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.metrics'`

- [ ] **Step 3: Write the metrics module**

Create `eval/metrics.py`:

```python
"""Statistical helpers for evaluation metrics."""

import statistics


def compute_percentiles(values: list[float]) -> dict[str, float]:
    """Compute min, max, mean, p50, p90, p99 for a list of numeric values."""
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def percentile(p: float) -> float:
        k = (n - 1) * (p / 100.0)
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])

    return {
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "mean": round(statistics.mean(sorted_vals), 1),
        "p50": round(percentile(50), 1),
        "p90": round(percentile(90), 1),
        "p99": round(percentile(99), 1),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/eval/test_metrics.py -v`
Expected: PASS — all 3 tests green

- [ ] **Step 5: Integrate percentiles into run_eval.py summary**

Modify `eval/run_eval.py` — add import at top (after existing imports):

```python
from metrics import compute_percentiles
```

Replace the `print_summary` function's latency section (lines ~262-274) to include percentile breakdown. In the `print_summary` function, after `print(f"\n--- Retrieval Recall ---")`, replace the avg retrieval latency line with:

```python
    retrieval_latencies = [q["retrieval"]["latency_ms"] for q in questions]
    agent_latencies = [
        q.get("agent_latency_ms", 0.0) for q in questions if q.get("agent_latency_ms", 0.0) > 0
    ]

    retrieval_pcts = compute_percentiles(retrieval_latencies)
    print(f"  Retrieval latency:      p50={retrieval_pcts['p50']:.0f}ms  "
          f"p90={retrieval_pcts['p90']:.0f}ms  p99={retrieval_pcts['p99']:.0f}ms")

    if agent_latencies:
        agent_pcts = compute_percentiles(agent_latencies)
        print(f"  Agent latency:          p50={agent_pcts['p50']:.0f}ms  "
              f"p90={agent_pcts['p90']:.0f}ms  p99={agent_pcts['p99']:.0f}ms")
```

Also update the results dict in the main loop (around line 230) to include the agent latency at the top level:

```python
    results.append({
        "id": qid,
        "question": question,
        "difficulty": difficulty,
        "retrieval": retrieval,
        "agent_answer": answer[:500],
        "agent_latency_ms": agent_result.get("latency_ms", 0.0),
        "scores": judge_scores,
    })
```

- [ ] **Step 6: Run tests to verify nothing is broken**

Run: `pytest tests/eval/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add eval/metrics.py tests/eval/test_metrics.py eval/run_eval.py
git commit -m "feat(eval): add latency percentile stats (p50/p90/p99) to eval summary"
```

---

### Task 2: Add Faithfulness Metric to LLM Judge

The key gap: the current judge scores against `expected_answer` only. Faithfulness requires scoring against the *retrieved context* — does the answer only use information from retrieved chunks?

**Files:**
- Modify: `eval/judges.py`
- Modify: `eval/run_eval.py`

- [ ] **Step 1: Write failing test for faithfulness scoring**

Create `tests/eval/test_judges.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "eval"))

from judges import score_faithfulness


@pytest.mark.asyncio
async def test_score_faithfulness_returns_expected_keys():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"faithfulness": 0.9, "reasoning": "Well grounded"}')]

    with patch("judges.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        mock_get.return_value = mock_client

        result = await score_faithfulness(
            question="What is DAU?",
            answer="DAU is daily active users.",
            retrieved_context=["DAU stands for Daily Active Users, counted by unique actions per day."],
        )

    assert "faithfulness" in result
    assert "reasoning" in result
    assert 0.0 <= result["faithfulness"] <= 1.0


@pytest.mark.asyncio
async def test_score_faithfulness_empty_context():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"faithfulness": 0.0, "reasoning": "No context provided"}')]

    with patch("judges.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        mock_get.return_value = mock_client

        result = await score_faithfulness(
            question="What is DAU?",
            answer="DAU is daily active users.",
            retrieved_context=[],
        )

    assert result["faithfulness"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/eval/test_judges.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_faithfulness'`

- [ ] **Step 3: Add faithfulness scoring to judges.py**

Add to `eval/judges.py` after the existing `RUBRIC_PROMPT` and `score_answer` function:

```python
FAITHFULNESS_PROMPT = """\
You are an expert evaluator for a RAG (Retrieval-Augmented Generation) system. Your job is to
assess whether an AI-generated answer is faithful to the retrieved context.

**Faithfulness** (0-1): Does the answer ONLY make claims that are supported by the retrieved
context? A score of 1.0 means every claim in the answer can be traced back to the context.
A score of 0.0 means the answer is entirely hallucinated or unsupported.

Specific checks:
- Any factual claim NOT in the retrieved context should reduce the score.
- Reasonable inferences from the context are acceptable (score ~0.8).
- Generic phrases ("This is important", "In summary") don't count as hallucinations.
- If the context is empty but the answer says "I don't have information", score 1.0.

Respond ONLY with a valid JSON object:
{
  "faithfulness": <float 0-1>,
  "reasoning": "<brief explanation>"
}
"""


async def score_faithfulness(
    question: str,
    answer: str,
    retrieved_context: list[str],
    model: str = "claude-sonnet-4-5-20250514",
) -> dict:
    """Score whether an answer is faithful to the retrieved context.

    Args:
        question: The original question.
        answer: The answer generated by the system.
        retrieved_context: List of retrieved text chunks.
        model: The Anthropic model to use for judging.

    Returns:
        A dict with keys: faithfulness, reasoning.
    """
    client = get_client()

    context_text = "\n\n---\n\n".join(retrieved_context) if retrieved_context else "(No context retrieved)"

    user_message = (
        f"## Question\n{question}\n\n"
        f"## Retrieved Context\n{context_text}\n\n"
        f"## Answer\n{answer}\n\n"
        "Please score the answer's faithfulness to the retrieved context."
    )

    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=FAITHFULNESS_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text.strip()

    try:
        scores = json.loads(raw_text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            scores = json.loads(match.group())
        else:
            return {"faithfulness": 0.0, "reasoning": f"Failed to parse: {raw_text[:200]}"}

    return {
        "faithfulness": float(scores.get("faithfulness", 0.0)),
        "reasoning": scores.get("reasoning", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/eval/test_judges.py -v`
Expected: PASS — both tests green

- [ ] **Step 5: Commit**

```bash
git add eval/judges.py tests/eval/test_judges.py
git commit -m "feat(eval): add faithfulness metric scoring against retrieved context"
```

---

### Task 3: Expose Retrieved Context via API for Evaluation

The eval runner needs to capture the retrieved chunks alongside the agent's answer. Currently `/api/search` returns chunks and `/api/chat` returns the answer, but we need them together. Add a debug endpoint.

**Files:**
- Modify: `src/pam/api/routes/chat.py`
- Modify: `eval/run_eval.py`

- [ ] **Step 1: Write failing test for debug chat endpoint**

Create `tests/api/test_chat_debug.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from pam.api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_chat_debug_returns_context(app):
    mock_result = MagicMock()
    mock_result.answer = "DAU is daily active users."
    mock_result.citations = []
    mock_result.token_usage = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    mock_result.latency_ms = 150.0
    mock_result.tool_calls = 1
    mock_result.retrieval_mode = "FACTUAL"
    mock_result.mode_confidence = 0.9
    mock_result.retrieved_context = ["DAU stands for Daily Active Users."]

    with patch("pam.api.routes.chat.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.answer.return_value = mock_result
        mock_get_agent.return_value = mock_agent

        app.dependency_overrides[mock_get_agent] = lambda: mock_agent

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat/debug", json={"message": "What is DAU?"})

    assert resp.status_code == 200
    data = resp.json()
    assert "retrieved_context" in data
    assert isinstance(data["retrieved_context"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_chat_debug.py -v`
Expected: FAIL with 404 — endpoint doesn't exist

- [ ] **Step 3: Add retrieved_context to AgentResponse**

Modify `src/pam/agent/agent.py` — add `retrieved_context` field to the `AgentResponse` dataclass (after line 80):

```python
@dataclass
class AgentResponse:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    tool_calls: int = 0
    retrieval_mode: str | None = None
    mode_confidence: float | None = None
    retrieved_context: list[str] = field(default_factory=list)
```

Then in the `answer` method, collect context from tool results. Find where tool results are appended to messages (look for the tool result handling in the loop). Add a list to collect chunks:

At the start of the `answer` method (after `tool_call_count = 0`), add:

```python
        all_retrieved_context: list[str] = []
```

In the tool result handling section (where `_execute_tool` results are processed), after the tool result is obtained, add context capture:

```python
            # After getting tool_result from _execute_tool:
            if tool_use.name in ("search_knowledge", "smart_search"):
                if isinstance(tool_result, str):
                    all_retrieved_context.append(tool_result)
```

In the `AgentResponse` return (around line 155), add:

```python
                    retrieved_context=all_retrieved_context,
```

- [ ] **Step 4: Add /chat/debug endpoint**

Modify `src/pam/api/routes/chat.py` — add a new response model and endpoint after the existing `ChatResponse`:

```python
class ChatDebugResponse(BaseModel):
    response: str
    citations: list[dict]
    conversation_id: str | None
    token_usage: dict
    latency_ms: float
    retrieval_mode: str | None = None
    mode_confidence: float | None = None
    retrieved_context: list[str] = []


@router.post("/chat/debug", response_model=ChatDebugResponse)
async def chat_debug(
    request: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
    _user: User | None = Depends(get_current_user),
):
    """Chat endpoint that also returns retrieved context for evaluation."""
    conversation_id = request.conversation_id or str(uuid.uuid4())

    kwargs: dict = {}
    if request.conversation_history:
        kwargs["conversation_history"] = [{"role": m.role, "content": m.content} for m in request.conversation_history]
    if request.source_type:
        kwargs["source_type"] = request.source_type

    try:
        result: AgentResponse = await agent.answer(request.message, **kwargs)
    except Exception as e:
        logger.exception("chat_debug_error", message=request.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    return ChatDebugResponse(
        response=result.answer,
        citations=[
            {
                "document_title": c.document_title,
                "section_path": c.section_path,
                "source_url": c.source_url,
                "segment_id": c.segment_id,
            }
            for c in result.citations
        ],
        conversation_id=conversation_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
        retrieval_mode=result.retrieval_mode,
        mode_confidence=result.mode_confidence,
        retrieved_context=result.retrieved_context,
    )
```

- [ ] **Step 5: Update eval runner to use debug endpoint and score faithfulness**

Modify `eval/run_eval.py` — update the `evaluate_agent` function to use `/api/chat/debug` and capture context:

```python
async def evaluate_agent(
    client: httpx.AsyncClient,
    api_url: str,
    question: str,
) -> dict:
    """Call POST /api/chat/debug and capture the agent's answer + context."""
    start = time.perf_counter()
    try:
        resp = await client.post(
            f"{api_url}/api/chat/debug",
            json={"message": question},
            timeout=60.0,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

        if resp.status_code != 200:
            return {
                "answer": "",
                "retrieved_context": [],
                "latency_ms": latency_ms,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()
        answer = data.get("answer", data.get("response", ""))
        if not answer:
            message = data.get("message", {})
            answer = message.get("content", "") if isinstance(message, dict) else str(message)

        return {
            "answer": answer,
            "retrieved_context": data.get("retrieved_context", []),
            "latency_ms": latency_ms,
        }

    except httpx.RequestError as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return {
            "answer": "",
            "retrieved_context": [],
            "latency_ms": latency_ms,
            "error": str(exc),
        }
```

Update the main eval loop to score faithfulness. In `run_evaluation`, after the existing judge scoring block (around line 226), add:

```python
            # Step 4: Faithfulness scoring
            faithfulness_score = {"faithfulness": 0.0, "reasoning": "No answer or context"}
            retrieved_ctx = agent_result.get("retrieved_context", [])
            if answer and retrieved_ctx:
                print("  -> Scoring faithfulness...")
                try:
                    faithfulness_score = await score_faithfulness(question, answer, retrieved_ctx)
                    print(f"     Faithfulness: {faithfulness_score['faithfulness']:.2f}")
                except Exception as exc:
                    print(f"     Faithfulness error: {exc}")
```

Add the import at top of `run_eval.py`:

```python
from judges import score_answer, score_faithfulness
```

Add faithfulness to the results dict:

```python
            results.append({
                "id": qid,
                "question": question,
                "difficulty": difficulty,
                "retrieval": retrieval,
                "agent_answer": answer[:500],
                "agent_latency_ms": agent_result.get("latency_ms", 0.0),
                "retrieved_context_count": len(agent_result.get("retrieved_context", [])),
                "scores": judge_scores,
                "faithfulness": faithfulness_score,
            })
```

Update `print_summary` to include faithfulness:

```python
    # After the existing Answer Quality section:
    faithful = [q for q in questions if q["faithfulness"]["faithfulness"] > 0]
    if faithful:
        avg_faith = sum(q["faithfulness"]["faithfulness"] for q in faithful) / len(faithful)
    else:
        avg_faith = 0.0

    print(f"\n--- Faithfulness (Groundedness) ---")
    print(f"  Scored answers:     {len(faithful)}/{total}")
    print(f"  Avg faithfulness:   {avg_faith:.2f}")
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/eval/ tests/api/test_chat_debug.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/pam/agent/agent.py src/pam/api/routes/chat.py eval/run_eval.py
git commit -m "feat(eval): add /chat/debug endpoint and faithfulness scoring to eval runner"
```

---

### Task 4: DeepEval Integration for Standardized RAG Metrics

**Files:**
- Modify: `pyproject.toml`
- Create: `eval/conftest.py`
- Create: `eval/test_rag_quality.py`

- [ ] **Step 1: Add DeepEval dependency**

Modify `pyproject.toml` — add to `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "pytest-randomly>=3.0",
    "ruff>=0.5",
    "mypy>=1.10",
    "pre-commit>=3.0",
]
eval = [
    "deepeval>=2.0",
]
```

- [ ] **Step 2: Install the new dependency**

Run: `pip install -e ".[eval]"`
Expected: deepeval installs successfully

- [ ] **Step 3: Create eval conftest with fixtures**

Create `eval/conftest.py`:

```python
"""Pytest fixtures for DeepEval RAG evaluation."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def evaluation_questions() -> list[dict]:
    """Load evaluation questions from questions.json."""
    questions_path = Path(__file__).parent / "questions.json"
    with open(questions_path) as f:
        return json.load(f)


@pytest.fixture
def synthetic_questions() -> list[dict]:
    """Load synthetic questions if available."""
    path = Path(__file__).parent / "datasets" / "synthetic_questions.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []
```

- [ ] **Step 4: Create DeepEval test file**

Create `eval/test_rag_quality.py`:

```python
"""DeepEval-based RAG quality tests.

Run with: pytest eval/test_rag_quality.py -v -m "not integration"

These tests use pre-recorded evaluation data. For live API tests,
use: python eval/run_eval.py
"""

import json
from pathlib import Path

import pytest

try:
    from deepeval import assert_test
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
    )
    from deepeval.test_case import LLMTestCase

    DEEPEVAL_AVAILABLE = True
except ImportError:
    DEEPEVAL_AVAILABLE = False


pytestmark = pytest.mark.skipif(not DEEPEVAL_AVAILABLE, reason="deepeval not installed")


EVAL_RESULTS_PATH = Path(__file__).parent / "datasets" / "last_eval_results.json"


def load_eval_results() -> list[dict]:
    """Load results from the last run_eval.py execution."""
    if not EVAL_RESULTS_PATH.exists():
        pytest.skip(
            "No eval results found. Run: python eval/run_eval.py --output eval/datasets/last_eval_results.json"
        )
    with open(EVAL_RESULTS_PATH) as f:
        data = json.load(f)
    return data.get("questions", [])


@pytest.fixture(params=load_eval_results() if EVAL_RESULTS_PATH.exists() else [], ids=lambda q: q.get("id", "?"))
def eval_case(request) -> dict:
    return request.param


def test_faithfulness(eval_case):
    """Answer must be grounded in retrieved context."""
    if not eval_case.get("agent_answer"):
        pytest.skip("No agent answer")

    # Build context from retrieved chunks (stored by run_eval)
    context = eval_case.get("retrieved_context", [])
    if not context:
        pytest.skip("No retrieved context available")

    test_case = LLMTestCase(
        input=eval_case["question"],
        actual_output=eval_case["agent_answer"],
        retrieval_context=context,
    )
    metric = FaithfulnessMetric(threshold=0.7, model="gpt-4o-mini")
    assert_test(test_case, [metric])


def test_answer_relevancy(eval_case):
    """Answer must be relevant to the question."""
    if not eval_case.get("agent_answer"):
        pytest.skip("No agent answer")

    test_case = LLMTestCase(
        input=eval_case["question"],
        actual_output=eval_case["agent_answer"],
    )
    metric = AnswerRelevancyMetric(threshold=0.7, model="gpt-4o-mini")
    assert_test(test_case, [metric])


def test_contextual_precision(eval_case):
    """Retrieved docs should be relevant and correctly ranked."""
    context = eval_case.get("retrieved_context", [])
    if not context:
        pytest.skip("No retrieved context available")

    test_case = LLMTestCase(
        input=eval_case["question"],
        actual_output=eval_case["agent_answer"],
        retrieval_context=context,
        expected_output=eval_case.get("expected_answer", ""),
    )
    metric = ContextualPrecisionMetric(threshold=0.6, model="gpt-4o-mini")
    assert_test(test_case, [metric])


def test_contextual_recall(eval_case):
    """Retrieval should find all relevant information."""
    context = eval_case.get("retrieved_context", [])
    if not context:
        pytest.skip("No retrieved context available")
    if not eval_case.get("expected_answer"):
        pytest.skip("No expected answer for recall comparison")

    test_case = LLMTestCase(
        input=eval_case["question"],
        actual_output=eval_case["agent_answer"],
        retrieval_context=context,
        expected_output=eval_case["expected_answer"],
    )
    metric = ContextualRecallMetric(threshold=0.6, model="gpt-4o-mini")
    assert_test(test_case, [metric])
```

- [ ] **Step 5: Create the datasets directory**

Run: `mkdir -p eval/datasets && echo '[]' > eval/datasets/synthetic_questions.json`

- [ ] **Step 6: Verify DeepEval tests are discovered**

Run: `pytest eval/test_rag_quality.py --collect-only`
Expected: Tests are collected (may be skipped if no results file yet, which is fine)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml eval/conftest.py eval/test_rag_quality.py eval/datasets/
git commit -m "feat(eval): add DeepEval integration for standardized RAG metrics"
```

---

### Task 5: Synthetic Question Generator

**Files:**
- Create: `eval/synthetic_gen.py`

- [ ] **Step 1: Write failing test for synthetic generation**

Create `tests/eval/test_synthetic_gen.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "eval"))

from synthetic_gen import generate_qa_pair, build_prompt_for_chunk


def test_build_prompt_for_chunk():
    chunk = "DAU is defined as the count of unique users who performed at least one qualifying action."
    prompt = build_prompt_for_chunk(chunk, "metrics-definitions.md")
    assert "DAU" in prompt
    assert "metrics-definitions.md" in prompt
    assert "question" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_qa_pair():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"question": "What is DAU?", "expected_answer": "DAU is the count of unique users who performed at least one qualifying action.", "difficulty": "simple"}')]

    with patch("synthetic_gen.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        mock_get.return_value = mock_client

        result = await generate_qa_pair(
            chunk_text="DAU is defined as the count of unique users.",
            document_title="metrics.md",
        )

    assert "question" in result
    assert "expected_answer" in result
    assert "difficulty" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/eval/test_synthetic_gen.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the synthetic generator**

Create `eval/synthetic_gen.py`:

```python
#!/usr/bin/env python3
"""Generate synthetic Q&A evaluation pairs from ingested documents.

Reads documents from the PAM API and uses Claude to generate question-answer
pairs suitable for evaluation.

Usage:
    python eval/synthetic_gen.py --api-url http://localhost:8000 --count 50
"""

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judges import get_client


GENERATION_PROMPT = """\
You are an expert at creating evaluation question-answer pairs for a business knowledge Q&A system.

Given a text chunk from a document, generate a question that:
1. Can be answered using ONLY the information in the chunk
2. Tests understanding, not just keyword matching
3. Varies in difficulty (simple factual recall, medium synthesis, complex reasoning)

Respond ONLY with a JSON object:
{
  "question": "<natural question a business user would ask>",
  "expected_answer": "<complete answer derived from the chunk>",
  "difficulty": "<simple|medium|complex>"
}
"""


def build_prompt_for_chunk(chunk_text: str, document_title: str) -> str:
    """Build the user prompt for Q&A generation from a chunk."""
    return (
        f"## Document: {document_title}\n\n"
        f"## Text Chunk\n{chunk_text}\n\n"
        "Generate a question-answer pair from this chunk."
    )


async def generate_qa_pair(
    chunk_text: str,
    document_title: str,
    model: str = "claude-sonnet-4-5-20250514",
) -> dict:
    """Generate a single Q&A pair from a document chunk."""
    client = get_client()

    response = await client.messages.create(
        model=model,
        max_tokens=512,
        system=GENERATION_PROMPT,
        messages=[{"role": "user", "content": build_prompt_for_chunk(chunk_text, document_title)}],
    )

    raw_text = response.content[0].text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"question": "", "expected_answer": "", "difficulty": "simple", "error": raw_text[:200]}


async def fetch_chunks(api_url: str, sample_size: int = 50) -> list[dict]:
    """Fetch document chunks from the PAM API for generation."""
    async with httpx.AsyncClient() as client:
        # Get list of documents
        resp = await client.get(f"{api_url}/api/documents", timeout=30.0)
        if resp.status_code != 200:
            print(f"Error fetching documents: {resp.status_code}")
            return []

        documents = resp.json()
        if isinstance(documents, dict):
            documents = documents.get("items", documents.get("documents", []))

        chunks = []
        for doc in documents:
            doc_id = doc.get("id")
            if not doc_id:
                continue
            resp = await client.get(f"{api_url}/api/documents/{doc_id}", timeout=30.0)
            if resp.status_code == 200:
                doc_data = resp.json()
                segments = doc_data.get("segments", [])
                for seg in segments:
                    content = seg.get("content", "")
                    if len(content) > 100:  # Skip very short chunks
                        chunks.append({
                            "content": content,
                            "document_title": doc.get("title", "Unknown"),
                        })

        # Sample if we have more than needed
        if len(chunks) > sample_size:
            chunks = random.sample(chunks, sample_size)

        return chunks


async def generate_dataset(api_url: str, count: int, output_path: str) -> None:
    """Generate a synthetic evaluation dataset."""
    print(f"Fetching chunks from {api_url}...")
    chunks = await fetch_chunks(api_url, sample_size=count)

    if not chunks:
        print("No chunks found. Make sure documents are ingested.")
        return

    print(f"Generating {len(chunks)} Q&A pairs...")
    questions = []

    for i, chunk in enumerate(chunks):
        print(f"  [{i + 1}/{len(chunks)}] Generating from: {chunk['document_title'][:40]}...")
        qa = await generate_qa_pair(chunk["content"], chunk["document_title"])
        if qa.get("question") and qa.get("expected_answer"):
            qa["id"] = f"syn_{i + 1:03d}"
            qa["source_document"] = chunk["document_title"]
            questions.append(qa)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(questions, f, indent=2)

    print(f"\nGenerated {len(questions)} Q&A pairs -> {out}")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic eval questions from ingested docs")
    parser.add_argument("--api-url", default=os.environ.get("PAM_API_URL", "http://localhost:8000"))
    parser.add_argument("--count", type=int, default=50, help="Number of Q&A pairs to generate")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "datasets" / "synthetic_questions.json"),
    )
    args = parser.parse_args()

    asyncio.run(generate_dataset(args.api_url, args.count, args.output))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/eval/test_synthetic_gen.py -v`
Expected: PASS — both tests green

- [ ] **Step 5: Commit**

```bash
git add eval/synthetic_gen.py tests/eval/test_synthetic_gen.py
git commit -m "feat(eval): add synthetic Q&A generator from ingested documents"
```

---

### Task 6: Load Testing with Locust

**Files:**
- Modify: `pyproject.toml`
- Create: `eval/load_test.py`

- [ ] **Step 1: Add locust dependency**

Modify `pyproject.toml` — extend the `eval` optional deps:

```toml
eval = [
    "deepeval>=2.0",
    "locust>=2.20",
]
```

- [ ] **Step 2: Install**

Run: `pip install -e ".[eval]"`

- [ ] **Step 3: Create the locust load test**

Create `eval/load_test.py`:

```python
"""Locust load test for PAM Context API.

Usage:
    # Web UI:
    locust -f eval/load_test.py --host http://localhost:8000

    # Headless (CI-friendly):
    locust -f eval/load_test.py --host http://localhost:8000 \
        --headless -u 10 -r 2 --run-time 60s \
        --csv eval/datasets/load_results
"""

import json
import random
from pathlib import Path

from locust import HttpUser, between, task

# Load questions for realistic query mix
_questions_path = Path(__file__).parent / "questions.json"
_questions = []
if _questions_path.exists():
    with open(_questions_path) as f:
        _questions = json.load(f)

# Also load synthetic if available
_synthetic_path = Path(__file__).parent / "datasets" / "synthetic_questions.json"
if _synthetic_path.exists():
    with open(_synthetic_path) as f:
        _synth = json.load(f)
        if _synth:
            _questions.extend(_synth)

# Fallback
if not _questions:
    _questions = [
        {"question": "How is DAU defined?"},
        {"question": "What is the conversion rate formula?"},
        {"question": "What data source feeds the retention dashboard?"},
    ]


class PAMSearchUser(HttpUser):
    """Simulates users hitting the search endpoint."""

    wait_time = between(0.5, 2.0)

    @task(3)
    def search(self):
        q = random.choice(_questions)
        self.client.post(
            "/api/search",
            json={"query": q["question"], "top_k": 5},
            name="/api/search",
        )

    @task(1)
    def chat(self):
        q = random.choice(_questions)
        self.client.post(
            "/api/chat",
            json={"message": q["question"]},
            name="/api/chat",
            timeout=60,
        )
```

- [ ] **Step 4: Verify locust can discover the test**

Run: `locust -f eval/load_test.py --list`
Expected: Shows `PAMSearchUser` class

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml eval/load_test.py
git commit -m "feat(eval): add locust load test for search and chat endpoints"
```

---

### Task 7: CI Quality Gate

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `eval/run_eval.py`

- [ ] **Step 1: Add exit code support to run_eval.py**

Modify `eval/run_eval.py` — add a `--fail-under` argument and exit code. Update the `main()` function:

```python
def main():
    parser = argparse.ArgumentParser(
        description="PAM Context Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("PAM_API_URL", "http://localhost:8000"),
        help="Base URL of the PAM API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--questions-file",
        default=str(Path(__file__).resolve().parent / "questions.json"),
        help="Path to the evaluation questions JSON file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to save the full results JSON (optional)",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Fail with exit code 1 if average score is below this threshold (0.0-1.0)",
    )
    args = parser.parse_args()

    results = asyncio.run(run_evaluation(args.api_url, args.questions_file))

    print_summary(results)

    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nFull results saved to {output_path}")

    # Quality gate
    if args.fail_under is not None:
        questions = results["questions"]
        scored = [q for q in questions if q["scores"]["average_score"] > 0]
        if scored:
            avg = sum(q["scores"]["average_score"] for q in scored) / len(scored)
        else:
            avg = 0.0

        if avg < args.fail_under:
            print(f"\nFAILED: Average score {avg:.2f} is below threshold {args.fail_under}")
            sys.exit(1)
        else:
            print(f"\nPASSED: Average score {avg:.2f} meets threshold {args.fail_under}")
```

- [ ] **Step 2: Write test for fail-under behavior**

Create `tests/eval/test_run_eval.py`:

```python
import pytest
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "eval"))

from run_eval import print_summary


def test_print_summary_no_questions(capsys):
    print_summary({"questions": []})
    captured = capsys.readouterr()
    assert "No questions to evaluate" in captured.out


def test_print_summary_with_results(capsys):
    results = {
        "questions": [
            {
                "id": "q001",
                "question": "Test?",
                "difficulty": "simple",
                "retrieval": {"has_relevant_result": True, "latency_ms": 50.0},
                "agent_answer": "Answer",
                "agent_latency_ms": 200.0,
                "scores": {
                    "factual_accuracy": 0.9,
                    "citation_presence": 0.8,
                    "completeness": 0.7,
                    "average_score": 0.8,
                    "reasoning": "Good",
                },
                "faithfulness": {"faithfulness": 0.85, "reasoning": "Grounded"},
            }
        ]
    }
    print_summary(results)
    captured = capsys.readouterr()
    assert "EVALUATION SUMMARY" in captured.out
    assert "p50=" in captured.out
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/eval/test_run_eval.py -v`
Expected: PASS

- [ ] **Step 4: Update CI workflow**

Modify `.github/workflows/ci.yml` — update the eval validation step:

```yaml
      - name: Validate eval framework
        run: |
          python -c "import json; json.load(open('eval/questions.json'))"
          python -c "import sys; sys.path.insert(0, 'eval'); from judges import score_answer, score_faithfulness"
          python -c "import sys; sys.path.insert(0, 'eval'); from run_eval import main"
          python -c "import sys; sys.path.insert(0, 'eval'); from metrics import compute_percentiles"
```

Add a comment documenting the integration eval step (not run in CI by default since it requires a live API):

```yaml
      # Integration eval (requires live API, not run by default):
      # python eval/run_eval.py --fail-under 0.6 --output eval/datasets/last_eval_results.json
```

- [ ] **Step 5: Commit**

```bash
git add eval/run_eval.py tests/eval/test_run_eval.py .github/workflows/ci.yml
git commit -m "feat(eval): add --fail-under quality gate and update CI validation"
```

---

### Task 8: Update Eval Questions to 20+ (Manual Expansion)

The existing 10 questions are good but limited. Add 10 more covering edge cases.

**Files:**
- Modify: `eval/questions.json`

- [ ] **Step 1: Add 10 new questions covering additional scenarios**

Append to `eval/questions.json` (add after `q010`, before the closing `]`):

```json
  {
    "id": "q011",
    "question": "What tables are in the analytics schema?",
    "expected_answer": "The analytics schema contains: analytics.user_activity_daily (daily user rollup from Airflow DAG), analytics.retention_cohorts_mv (materialized view refreshed every 6 hours), and analytics.event_volume_daily (daily event volume counts for monitoring instrumentation health).",
    "difficulty": "simple"
  },
  {
    "id": "q012",
    "question": "How does the retry logic work for failed ingestions?",
    "expected_answer": "Failed ingestions are retried 3 times with exponential backoff. After all retries are exhausted, the system alerts the on-call engineer via PagerDuty. The retry delay follows the pattern: 1st retry after 30 seconds, 2nd after 2 minutes, 3rd after 10 minutes.",
    "difficulty": "medium"
  },
  {
    "id": "q013",
    "question": "Compare DAU and MAU calculation methodologies.",
    "expected_answer": "DAU counts unique users with at least one qualifying action per calendar day (UTC), while MAU counts unique users with at least one qualifying action within a 30-day rolling window. Both exclude bot traffic and internal employee accounts. DAU is computed from the events.raw_events table daily, while MAU uses a 30-day window over analytics.user_activity_daily. The ratio DAU/MAU (stickiness) is a key engagement metric tracked on the retention dashboard.",
    "difficulty": "complex"
  },
  {
    "id": "q014",
    "question": "What happens when a Google Drive webhook fires?",
    "expected_answer": "When a Google Drive webhook fires, the event must be processed within 5 minutes of receipt per the SLA. The system fetches the changed file, computes a content hash (SHA-256) to detect actual content changes, and if the hash differs from the stored version, triggers the full ingestion pipeline: parse with Docling, chunk, embed, store in PostgreSQL and Elasticsearch, and optionally sync to the knowledge graph.",
    "difficulty": "medium"
  },
  {
    "id": "q015",
    "question": "I don't think we track anything. What events exist?",
    "expected_answer": "The system tracks multiple events across user flows. The signup flow alone tracks 7 events: signup_page_viewed, signup_form_started, signup_email_entered, signup_password_entered, signup_submitted, signup_email_verified, and signup_completed. Additional events are defined in the tracking plan owned by the Product Analytics team. Each event includes properties like user_anonymous_id, utm_source, utm_medium, utm_campaign, device_type, and browser.",
    "difficulty": "simple"
  },
  {
    "id": "q016",
    "question": "If the retention dashboard shows stale data, where should I look first?",
    "expected_answer": "Check the daily_user_rollup Airflow DAG first — it populates analytics.user_activity_daily which feeds the dashboard. Then check the materialized view analytics.retention_cohorts_mv refresh schedule (every 6 hours). If the DAG is healthy, check BigQuery for the last successful write to analytics.user_activity_daily. The raw data flows from Segment into events.raw_events, so a Segment outage could also cause staleness.",
    "difficulty": "complex"
  },
  {
    "id": "q017",
    "question": "What is a qualifying action for DAU?",
    "expected_answer": "A qualifying action for DAU is a page view, feature interaction, or API call performed by a user within a single calendar day (UTC). Bot traffic and internal employee accounts are excluded from the count.",
    "difficulty": "simple"
  },
  {
    "id": "q018",
    "question": "How do I add a new event to the tracking plan?",
    "expected_answer": "New events require approval from Sarah Chen (Senior Product Analyst), the tracking plan owner, via the event-change-request process in Jira. The Growth Engineering team is responsible for implementation. For schema migrations, a three-phase process applies: deprecation notice with sunset date, parallel tracking for at least 2 weeks, then removal after downstream migration is confirmed.",
    "difficulty": "medium"
  },
  {
    "id": "q019",
    "question": "What's the difference between the events.raw_events table and analytics.user_activity_daily?",
    "expected_answer": "events.raw_events is the raw event table populated directly from Segment — it contains individual event records. analytics.user_activity_daily is an aggregated table computed by the daily_user_rollup Airflow DAG — it rolls up raw events into per-user daily summaries. The aggregated table is what the retention dashboard reads from (via the retention_cohorts_mv materialized view).",
    "difficulty": "medium"
  },
  {
    "id": "q020",
    "question": "Walk me through troubleshooting a conversion rate drop that coincides with a deployment.",
    "expected_answer": "Steps: (1) Check the tracking plan changelog for any event modifications deployed in that release, (2) Compare raw event volumes in events.raw_events before and after the deployment timestamp, (3) Verify the conversion funnel query still references correct event names (checkout_success and pricing_page_viewed), (4) Check if the attribution window (30-day) was accidentally changed, (5) Use analytics.event_volume_daily to identify sudden volume drops indicating broken instrumentation vs. real behavior change, (6) Check browser console for JS errors on the checkout page that might prevent event firing, (7) Verify Segment is receiving events by checking Segment's live debugger.",
    "difficulty": "complex"
  }
```

- [ ] **Step 2: Validate JSON**

Run: `python -c "import json; qs = json.load(open('eval/questions.json')); print(f'{len(qs)} questions loaded')"`
Expected: `20 questions loaded`

- [ ] **Step 3: Commit**

```bash
git add eval/questions.json
git commit -m "feat(eval): expand evaluation questions from 10 to 20"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Latency percentiles (p50/p90/p99) — Task 1
- [x] Faithfulness metric against retrieved context — Task 2
- [x] API endpoint to expose retrieved context — Task 3
- [x] DeepEval integration (faithfulness, relevancy, precision, recall) — Task 4
- [x] Synthetic dataset generation — Task 5
- [x] Load testing (locust) — Task 6
- [x] CI quality gate — Task 7
- [x] Expanded question set — Task 8

**2. Placeholder scan:** No TBD/TODO/placeholders. All code blocks are complete.

**3. Type consistency:**
- `compute_percentiles` — consistent name in metrics.py, run_eval.py, and tests
- `score_faithfulness` — consistent signature in judges.py, run_eval.py, and tests
- `AgentResponse.retrieved_context` — list[str] in agent.py and ChatDebugResponse
- `generate_qa_pair` — consistent in synthetic_gen.py and tests
- `build_prompt_for_chunk` — consistent name across file

---

## Running the Full Suite

After all tasks are complete:

```bash
# 1. Unit tests (no API needed)
pytest tests/eval/ -v

# 2. Full eval against live API
docker compose up -d
python eval/run_eval.py --output eval/datasets/last_eval_results.json --fail-under 0.6

# 3. DeepEval metrics (uses saved results)
pytest eval/test_rag_quality.py -v

# 4. Generate synthetic questions
python eval/synthetic_gen.py --count 50

# 5. Load test
locust -f eval/load_test.py --host http://localhost:8000 --headless -u 10 -r 2 --run-time 60s

# 6. Re-run eval with expanded dataset
python eval/run_eval.py --questions-file eval/datasets/synthetic_questions.json --output eval/datasets/synthetic_eval_results.json
```
