import pytest

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
    assert "Faithfulness" in captured.out
