"""Task-level percentile bootstrap 95% CI for the mean of per-task values.

Used by ``scripts/aggregate.py`` to render the per-cell CIs reported in the
paper. The unit of uncertainty is the task (one observation per task), not
the trial — pass^3 and pass@3 are task-level indicators, and pass@1 is
already averaged within a task by the HumanEval estimator before bootstrap.

Implementation lives in ``chi_bench.aggregator`` so the same code is reachable
from the installed ``chi-bench`` package; this module is a thin re-export
matched to the older ``scripts/_wilson.py`` layout.
"""

from __future__ import annotations

from chi_bench.aggregator import (  # noqa: F401  (re-export)
    DEFAULT_BOOTSTRAP_ITERS,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CI_ALPHA,
    _bootstrap_ci as bootstrap_ci,
)
