"""Tests for chat endpoint Pydantic models."""

import pytest
from pydantic import ValidationError

from pam.api.routes.chat import ConversationMessage


class TestConversationMessage:
    def test_accepts_user_role(self):
        msg = ConversationMessage(role="user", content="hello")
        assert msg.role == "user"

    def test_accepts_assistant_role(self):
        msg = ConversationMessage(role="assistant", content="hi")
        assert msg.role == "assistant"

    def test_rejects_invalid_role(self):
        with pytest.raises(ValidationError):
            ConversationMessage(role="system", content="nope")

    def test_rejects_arbitrary_string(self):
        with pytest.raises(ValidationError):
            ConversationMessage(role="admin", content="nope")
