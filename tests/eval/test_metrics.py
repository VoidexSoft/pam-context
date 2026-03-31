import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "eval"))

from metrics import compute_percentiles


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
