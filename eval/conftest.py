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
