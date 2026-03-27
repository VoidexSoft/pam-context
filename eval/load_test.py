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
