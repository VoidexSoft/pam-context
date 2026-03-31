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
        return []
    with open(EVAL_RESULTS_PATH) as f:
        data = json.load(f)
    return data.get("questions", [])


_eval_results = load_eval_results()


@pytest.fixture(
    params=_eval_results
    if _eval_results
    else [
        pytest.param(
            None,
            marks=pytest.mark.skip(
                reason="No eval results found. Run: python eval/run_eval.py --output eval/datasets/last_eval_results.json"
            ),
        )
    ],
    ids=lambda q: q.get("id", "?") if isinstance(q, dict) else "skip",
)
def eval_case(request) -> dict:
    return request.param


def test_faithfulness(eval_case):
    """Answer must be grounded in retrieved context."""
    if not eval_case.get("agent_answer"):
        pytest.skip("No agent answer")

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
    if not eval_case.get("agent_answer"):
        pytest.skip("No agent answer")

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
    if not eval_case.get("agent_answer"):
        pytest.skip("No agent answer")

    test_case = LLMTestCase(
        input=eval_case["question"],
        actual_output=eval_case["agent_answer"],
        retrieval_context=context,
        expected_output=eval_case["expected_answer"],
    )
    metric = ContextualRecallMetric(threshold=0.6, model="gpt-4o-mini")
    assert_test(test_case, [metric])
