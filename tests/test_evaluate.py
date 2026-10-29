import numpy as np

from blotto.evaluate import (baseline_array, g1_round_robin, g2_round_robin, paired_comparison,
                             robustness_summary, weight_sensitivity)
from blotto.generators import generate
from blotto.vectorized import G2Field, as_alloc_array


def test_baselines_valid_and_round_robins_conserve():
    names, X = baseline_array()
    as_alloc_array(X)
    assert len(names) >= 20 and len(np.unique(X, axis=0)) == len(X)
    rr1 = g1_round_robin(names, X)
    M = np.array(rr1["matrix"])
    assert np.allclose(M + M.T, 15)
    rr2 = g2_round_robin(names[:8], X[:8])
    # exact round robin: average payout over all baselines equals 15/4
    assert np.isclose(np.mean([r["mean"] for r in rr2["rows"]]), 15 / 4)
    for r in rr2["rows"]:
        assert np.isclose(sum(r["pos"]), 1)


def test_paired_comparison_identical_is_zero():
    rng = np.random.default_rng(0)
    field = G2Field.from_population(generate("dirichlet", rng, 500), rng, 2000)
    X = np.array([[0, 10, 20, 30, 40], [0, 10, 20, 30, 40], [100, 0, 0, 0, 0]])
    res = paired_comparison(field, X)
    assert res[1]["diff"] == 0 and res[2]["verdict"] == "worse"


def test_robustness_and_sensitivity():
    S = np.array([[8.0, 7.0], [7.5, 7.5], [6.0, 9.0]])
    r = robustness_summary(S, ["a", "b"])
    assert list(r["worst"]) == [7.0, 7.5, 6.0] and r["worst_scenario"][2] == "a"
    ws = weight_sensitivity(S, np.random.default_rng(1), 500)
    assert np.isclose(ws["win_freq"].sum(), 1)
