import numpy as np
import pytest

from blotto.config import GameConfig
from blotto.optimize.best_response import g1_best_response_dp, g1_near_optimal, g1_top_k
from blotto.vectorized import all_allocations, g1_matrix, g1_scores, g1_tables


@pytest.mark.parametrize("seed", range(5))
def test_dp_matches_exhaustive_small_game(seed):
    cfg = GameConfig(values=(1, 2, 3, 4, 5), soldiers=20)
    rng = np.random.default_rng(seed)
    opps = rng.multinomial(20, rng.dirichlet(np.ones(5)), size=50)
    table = g1_tables(opps, cfg)
    alloc, val = g1_best_response_dp(table)
    allocs = all_allocations(cfg)
    brute = g1_matrix(allocs.astype(np.int64), opps, cfg).mean(1)
    assert val == pytest.approx(brute.max())
    assert alloc.sum() == 20
    assert g1_scores(alloc, table)[0] == pytest.approx(val)


def test_dp_matches_top1_default_game():
    rng = np.random.default_rng(9)
    opps = rng.multinomial(100, rng.dirichlet(np.ones(5)), size=300)
    table = g1_tables(opps)
    alloc, val = g1_best_response_dp(table)
    top, scores = g1_top_k(table, 5)
    assert scores[0] == pytest.approx(val)
    assert np.all(np.diff(scores) <= 1e-12)
    near, ns = g1_near_optimal(table, 0.0)
    assert any((alloc == n).all() for n in near)


def test_best_response_vs_single_opponent():
    # vs [20]*5: 21 soldiers on castles 2-5 (84) wins 14 points; castle 1 is lost
    table = g1_tables(np.array([[20, 20, 20, 20, 20]]))
    alloc, val = g1_best_response_dp(table)
    assert val == pytest.approx(14)
    assert np.all(alloc[1:] >= 21)
