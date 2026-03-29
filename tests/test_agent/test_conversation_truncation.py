"""Tests for conversation history token-based truncation."""

import pytest

from pam.agent.agent import _truncate_history


def test_short_history_unchanged():
    """History under the token budget passes through unchanged."""
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "What is X?"},
    ]
    result = _truncate_history(messages, max_chars=10_000)
    assert result == messages


def test_long_history_truncated():
    """History exceeding the budget drops oldest pairs, keeps latest user message."""
    messages = [
        {"role": "user", "content": "A" * 5000},
        {"role": "assistant", "content": "B" * 5000},
        {"role": "user", "content": "C" * 5000},
        {"role": "assistant", "content": "D" * 5000},
        {"role": "user", "content": "latest question"},
    ]
    result = _truncate_history(messages, max_chars=12_000)
    # Should drop the oldest pair(s) but keep "latest question"
    assert result[-1]["content"] == "latest question"
    total_chars = sum(len(m["content"]) for m in result)
    assert total_chars <= 12_000


def test_empty_history_unchanged():
    """Empty history returns empty."""
    assert _truncate_history([], max_chars=10_000) == []


def test_single_message_kept():
    """A single oversized message is kept (we never drop the last user message)."""
    messages = [{"role": "user", "content": "X" * 50_000}]
    result = _truncate_history(messages, max_chars=10_000)
    assert len(result) == 1
    assert result[0]["content"] == "X" * 50_000
