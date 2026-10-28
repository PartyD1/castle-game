import numpy as np
import pytest

from blotto.config import GameConfig
from blotto.scoring import score_four_way, score_head_to_head
from blotto.vectorized import (G2Field, all_allocations, as_alloc_array, g1_matrix,
                               g1_scores, g1_tables, g2_play, sample_triples)


def coarse_pop(rng, n, cfg=GameConfig(), step=10):
    """Allocations on a coarse grid so castle and rank ties are frequent."""
    units = cfg.soldiers // step
    return rng.multinomial(units, np.ones(cfg.n_castles) / cfg.n_castles, size=n) * step


def test_as_alloc_array_rejects_bad_rows():
    with pytest.raises(ValueError):
        as_alloc_array([[20, 20, 20, 20, 21]])
    assert as_alloc_array([20, 20, 20, 20, 20]).shape == (1, 5)


def test_g1_matrix_matches_scalar_and_conserves():
    rng = np.random.default_rng(0)
    A, B = coarse_pop(rng, 40), coarse_pop(rng, 30)
    M = g1_matrix(A, B)
    for i in range(len(A)):
        for j in range(len(B)):
            assert M[i, j] == pytest.approx(score_head_to_head(A[i], B[j])[0])
    assert np.allclose(M + g1_matrix(B, A).T, 15)


def test_g1_table_scores_equal_matrix_mean():
    rng = np.random.default_rng(1)
    opps = coarse_pop(rng, 500, step=5)
    cands = coarse_pop(rng, 50, step=5)
    assert np.allclose(g1_scores(cands, g1_tables(opps)), g1_matrix(cands, opps).mean(1))


def test_g1_weighted_table():
    opps = np.array([[100, 0, 0, 0, 0], [0, 0, 0, 0, 100]])
    t = g1_tables(opps, weights=np.array([3, 1]))
    cand = np.array([[0, 0, 0, 50, 50]])
    exact = 0.75 * score_head_to_head(cand[0], opps[0])[0] + 0.25 * score_head_to_head(cand[0], opps[1])[0]
    assert g1_scores(cand, t)[0] == pytest.approx(exact)


def test_g2_play_matches_scalar():
    rng = np.random.default_rng(2)
    groups = coarse_pop(rng, 4 * 3000, step=20).reshape(3000, 4, 5)
    pts, pay = g2_play(groups)
    assert np.allclose(pts.sum(1), 15) and np.allclose(pay.sum(1), 15)
    for g in range(300):
        ref = score_four_way(groups[g])
        assert np.allclose(pts[g], ref["castle_points"])
        assert np.allclose(pay[g], ref["payouts"])


def test_g2_field_matches_scalar_and_positions_sum_to_one():
    rng = np.random.default_rng(3)
    opps = coarse_pop(rng, 200, step=20)
    tri = sample_triples(rng, len(opps), 2000)
    field = G2Field(opps[tri])
    cands = coarse_pop(rng, 7, step=20)
    samples = field.payout_samples(cands)
    for b in range(len(cands)):
        for k in range(0, 2000, 37):
            ref = score_four_way([cands[b], *opps[tri[k]]])
            assert samples[b, k] == pytest.approx(ref["payouts"][0])
    res = field.evaluate(cands)
    assert np.allclose(res["pos"].sum(1), 1)
    assert np.allclose(res["mean"], samples.mean(1))
    expected_from_pos = res["pos"] @ np.array([9, 4, 2, 0])
    assert np.allclose(expected_from_pos, res["mean"])


def test_sample_triples_distinct():
    t = sample_triples(np.random.default_rng(4), 3, 1000)
    assert np.all(np.sort(t, 1) == [0, 1, 2])


def test_all_allocations_small_and_default_count():
    small = all_allocations(GameConfig(values=(1, 2, 3), soldiers=4))
    assert len(small) == 15 and np.all(small.sum(1) == 4) and len(np.unique(small, axis=0)) == 15
    assert len(all_allocations()) == 4_598_126


def test_custom_config_four_way_conservation():
    cfg = GameConfig(values=(3, 1, 4, 1, 5), soldiers=50, payouts=(10, 5, 1, 0))
    rng = np.random.default_rng(5)
    groups = coarse_pop(rng, 4 * 500, cfg, step=10).reshape(500, 4, 5)
    pts, pay = g2_play(groups, cfg)
    assert np.allclose(pts.sum(1), 14) and np.allclose(pay.sum(1), 16)
