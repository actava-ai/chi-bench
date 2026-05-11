"""Wilson score 95% confidence interval for binomial proportions.

Used by scripts/aggregate.py to render the per-cell CIs in paper Table 1
(footnote: "Wilson on n=225 trials for pass@1 and n=75 tasks for pass@3 /
pass^3"). Matches https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval.
"""

from __future__ import annotations

import math


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (low, high) of the Wilson 95% CI for k successes in n trials."""
    if n <= 0:
        return (0.0, 0.0)
    p_hat = k / n
    denom = 1 + z * z / n
    centre = p_hat + z * z / (2 * n)
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return (max(0.0, lo), min(1.0, hi))
