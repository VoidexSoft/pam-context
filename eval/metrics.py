"""Statistical helpers for evaluation metrics."""

import statistics


def compute_percentiles(values: list[float]) -> dict[str, float]:
    """Compute min, max, mean, p50, p90, p99 for a list of numeric values."""
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def percentile(p: float) -> float:
        k = n * (p / 100.0) - 0.5
        if k < 0:
            return sorted_vals[0]
        f = int(k)
        c = min(f + 1, n - 1)
        d = k - f
        return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])

    return {
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "mean": round(statistics.mean(sorted_vals), 1),
        "p50": round(percentile(50), 1),
        "p90": round(percentile(90), 1),
        "p99": round(percentile(99), 1),
    }
