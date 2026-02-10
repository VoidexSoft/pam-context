"""Tests for pam.common.logging — correlation IDs and CostTracker."""

from pam.common.logging import (
    CostTracker,
    correlation_id_var,
    get_correlation_id,
    set_correlation_id,
)


class TestCorrelationId:
    def test_set_and_get(self):
        cid = set_correlation_id("test-123")
        assert cid == "test-123"
        assert get_correlation_id() == "test-123"

    def test_auto_generate(self):
        cid = set_correlation_id()
        assert len(cid) == 16
        assert get_correlation_id() == cid

    def test_default_empty(self):
        # Reset to default
        token = correlation_id_var.set("")
        try:
            assert get_correlation_id() == ""
        finally:
            correlation_id_var.reset(token)


class TestCostTracker:
    def test_empty_tracker(self):
        tracker = CostTracker()
        assert tracker.total_cost == 0.0
        assert tracker.total_tokens == 0
        assert tracker.calls == []

    def test_log_llm_call(self):
        tracker = CostTracker()
        tracker.log_llm_call(
            model="claude-sonnet-4-5-20250514",
            input_tokens=1000,
            output_tokens=500,
            latency_ms=200.0,
        )
        assert len(tracker.calls) == 1
        assert tracker.calls[0]["model"] == "claude-sonnet-4-5-20250514"
        assert tracker.calls[0]["input_tokens"] == 1000
        assert tracker.calls[0]["output_tokens"] == 500
        assert tracker.calls[0]["latency_ms"] == 200.0
        assert tracker.total_tokens == 1500
        assert tracker.total_cost > 0

    def test_log_embedding_call(self):
        tracker = CostTracker()
        tracker.log_embedding_call(
            model="text-embedding-3-large",
            input_tokens=500,
            latency_ms=50.0,
        )
        assert len(tracker.calls) == 1
        assert tracker.calls[0]["model"] == "text-embedding-3-large"
        assert tracker.total_tokens == 500
        assert tracker.total_cost > 0

    def test_multiple_calls_accumulate(self):
        tracker = CostTracker()
        tracker.log_llm_call("claude-sonnet-4-5-20250514", 100, 50, 100.0)
        tracker.log_llm_call("claude-sonnet-4-5-20250514", 200, 100, 150.0)
        assert len(tracker.calls) == 2
        assert tracker.total_tokens == 450  # 100+50+200+100

    def test_estimate_cost_known_model(self):
        cost = CostTracker._estimate_cost("claude-sonnet-4-5-20250514", 1_000_000, 0)
        assert cost == 3.0  # $3 per 1M input tokens

    def test_estimate_cost_unknown_model_uses_default(self):
        cost = CostTracker._estimate_cost("unknown-model", 1_000_000, 0)
        assert cost == 3.0  # falls back to sonnet pricing

    def test_estimate_embedding_cost(self):
        cost = CostTracker._estimate_embedding_cost("text-embedding-3-large", 1_000_000)
        assert cost == 0.13
