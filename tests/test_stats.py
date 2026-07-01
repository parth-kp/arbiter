import math

import pytest

from arbiter.stats import paired_permutation_test, pass_at_k, pass_hat_k, percentile, wilson


def test_wilson_matches_known_values():
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert wilson(0, 0) == (0.0, 0.0)
    assert wilson(0, 5)[0] == 0.0 and wilson(5, 5)[1] == 1.0


def test_pass_at_k_and_pass_hat_k_unbiased_estimators():
    assert pass_at_k(3, 1, 1) == pytest.approx(1 / 3)
    assert pass_at_k(3, 1, 3) == 1.0
    assert pass_at_k(4, 0, 2) == 0.0
    assert pass_hat_k(3, 2, 2) == pytest.approx(1 / 3)
    assert pass_hat_k(3, 3, 3) == 1.0 and pass_hat_k(3, 2, 3) == 0.0
    n, c = 5, 3
    assert pass_hat_k(n, c, 1) == pytest.approx(c / n) == pytest.approx(pass_at_k(n, c, 1))


def test_pass_hat_k_rejects_k_above_n():
    with pytest.raises(ValueError):
        pass_hat_k(2, 1, 3)


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([10], 0.95) == 10
    assert percentile([], 0.5) == 0.0


def test_permutation_test_exact_and_null():
    assert paired_permutation_test([0, 0, 0]) == 1.0
    assert paired_permutation_test([1.0] * 6) == pytest.approx(2 / 64)
    assert paired_permutation_test([1, -1, 1, -1]) == 1.0
    big = [1.0] * 30
    assert paired_permutation_test(big) < 0.001
    assert math.isclose(paired_permutation_test(big), paired_permutation_test(big))
