from scripts._wilson import wilson_score_interval


def test_wilson_zero_successes():
    lo, hi = wilson_score_interval(k=0, n=10)
    assert lo == 0.0
    assert 0.25 < hi < 0.35  # paper-typical floor


def test_wilson_full_successes():
    lo, hi = wilson_score_interval(k=10, n=10)
    assert 0.65 < lo < 0.75
    assert hi == 1.0


def test_wilson_half_successes_symmetric():
    lo, hi = wilson_score_interval(k=5, n=10)
    # 95% CI for p=0.5 with n=10 is roughly (0.237, 0.763)
    assert 0.20 < lo < 0.28
    assert 0.72 < hi < 0.80


def test_wilson_paper_example_pass1():
    # Paper Table 1: pass@1 = 28.0% on n=225 trials (75 tasks × 3 trials)
    # Wilson 95% CI: [-5.5, +6.2] from paper -> 22.5% to 34.2%
    lo, hi = wilson_score_interval(k=63, n=225)  # 28.0% × 225 ≈ 63
    assert 0.22 < lo < 0.24
    assert 0.34 < hi < 0.36


def test_wilson_n_zero_returns_zero_zero():
    lo, hi = wilson_score_interval(k=0, n=0)
    assert lo == 0.0
    assert hi == 0.0
