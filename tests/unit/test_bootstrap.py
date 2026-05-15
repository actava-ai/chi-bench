"""Tests for the task-level percentile bootstrap CI used by the aggregator."""

from scripts._bootstrap import bootstrap_ci


def test_bootstrap_empty_returns_zero_zero():
    lo, hi = bootstrap_ci([], iters=1000, seed=0)
    assert lo == 0.0
    assert hi == 0.0


def test_bootstrap_all_zeros_collapses_to_zero():
    lo, hi = bootstrap_ci([0.0] * 25, iters=1000, seed=0)
    assert lo == 0.0
    assert hi == 0.0


def test_bootstrap_all_ones_collapses_to_one():
    lo, hi = bootstrap_ci([1.0] * 25, iters=1000, seed=0)
    assert lo == 1.0
    assert hi == 1.0


def test_bootstrap_seed_is_deterministic():
    values = [0.0, 1.0 / 3, 2.0 / 3, 1.0] * 6  # 24 values, mean 0.5
    lo_a, hi_a = bootstrap_ci(values, iters=1000, seed=0)
    lo_b, hi_b = bootstrap_ci(values, iters=1000, seed=0)
    assert (lo_a, hi_a) == (lo_b, hi_b)
    # Different seed should change the interval (sanity, not a property
    # guarantee — but two distinct seeds on this data move the endpoints).
    lo_c, hi_c = bootstrap_ci(values, iters=1000, seed=42)
    assert (lo_a, hi_a) != (lo_c, hi_c)


def test_bootstrap_brackets_the_mean():
    # 75-task vector with mean 28/75 (= paper Table 2 best overall pass@1).
    values = [1.0] * 21 + [0.0] * 54
    lo, hi = bootstrap_ci(values, iters=1000, seed=0)
    mean = 21.0 / 75
    assert lo <= mean <= hi
    # Standard error for a Bernoulli with p=0.28, n=75 is ~0.052, so the
    # 95% percentile interval should be within ~0.1 of the mean on each side.
    assert (mean - lo) < 0.12
    assert (hi - mean) < 0.12


def test_bootstrap_alpha_widens_interval_for_smaller_alpha():
    values = [1.0] * 21 + [0.0] * 54
    lo_95, hi_95 = bootstrap_ci(values, iters=1000, seed=0, alpha=0.05)
    lo_99, hi_99 = bootstrap_ci(values, iters=1000, seed=0, alpha=0.01)
    assert lo_99 <= lo_95
    assert hi_99 >= hi_95
