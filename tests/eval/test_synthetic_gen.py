import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "eval"))

from synthetic_gen import build_prompt_for_chunk, generate_qa_pair


def test_build_prompt_for_chunk():
    chunk = "DAU is defined as the count of unique users who performed at least one qualifying action."
    prompt = build_prompt_for_chunk(chunk, "metrics-definitions.md")
    assert "DAU" in prompt
    assert "metrics-definitions.md" in prompt
    assert "question" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_qa_pair():
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=(
                '{"question": "What is DAU?", "expected_answer": '
                '"DAU is the count of unique users who performed at least one qualifying action.", '
                '"difficulty": "simple"}'
            )
        )
    ]

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
