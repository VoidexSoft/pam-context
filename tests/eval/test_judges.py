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
