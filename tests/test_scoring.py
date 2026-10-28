import numpy as np
import pytest

from blotto.config import GameConfig
from blotto.scoring import (calculate_rank_payouts, score_four_way,
                            score_head_to_head, validate_allocation)


# --- validate_allocation -------------------------------------------------

@pytest.mark.parametrize("alloc", [
    [20, 20, 20, 20, 20],
    [100, 0, 0, 0, 0],
    [0, 0, 0, 0, 100],
    np.array([10, 15, 20, 25, 30]),
    [10.0, 15.0, 20.0, 25.0, 30.0],
])
def test_valid_allocations(alloc):
    out = validate_allocation(alloc)
    assert out.sum() == 100 and out.dtype == np.int64


@pytest.mark.parametrize("alloc, msg", [
    ([20, 20, 20, 20], "exactly 5"),
    ([20, 20, 20, 20, 20, 0], "exactly 5"),
    ([21, 20, 20, 20, 20], "sum to 100"),
    ([19, 20, 20, 20, 20], "sum to 100"),
    ([-10, 30, 20, 30, 30], "nonnegative"),
    ([20.5, 19.5, 20, 20, 20], "whole numbers"),
    ([float("nan"), 20, 20, 20, 40], "whole numbers"),
    (["a", "b", "c", "d", "e"], "numeric"),
    ([True, False, False, False, False], "booleans"),
    ([[20, 20, 20, 20, 20]], "exactly 5"),
])
def test_invalid_allocations(alloc, msg):
    with pytest.raises(ValueError, match=msg):
        validate_allocation(alloc)


# --- head to head ------------------------------------------------------

def test_h2h_identical_split_everything():
    assert score_head_to_head([20] * 5, [20] * 5) == (7.5, 7.5)


def test_h2h_zero_vs_zero_ties():
    a = [0, 0, 0, 50, 50]
    b = [0, 0, 100, 0, 0]
    # castles 1,2 tie at zero (0.5 + 1), castle 3 to b, castles 4,5 to a
    assert score_head_to_head(a, b) == (1.5 + 9, 1.5 + 3)


def test_h2h_fractional_points():
    pa, pb = score_head_to_head([0, 25, 25, 25, 25], [1, 24, 25, 25, 25])
    assert (pa, pb) == (2 + 1.5 + 2 + 2.5, 1 + 1.5 + 2 + 2.5)


def test_h2h_always_sums_to_15():
    rng = np.random.default_rng(0)
    for _ in range(2000):
        a = rng.multinomial(100, np.ones(5) / 5)
        b = rng.multinomial(100, rng.dirichlet(np.ones(5)))
        assert sum(score_head_to_head(a, b)) == pytest.approx(15)


def test_h2h_custom_values():
    cfg = GameConfig(values=(2, 2, 2), soldiers=9)
    assert score_head_to_head([3, 3, 3], [9, 0, 0], cfg) == (4, 2)


# --- rank payouts --------------------------------------------------------

@pytest.mark.parametrize("scores, expected", [
    ([10, 3, 2, 0], [9, 4, 2, 0]),                        # no ties
    ([5, 5, 3, 2], [6.5, 6.5, 2, 0]),                     # 2-way tie for first
    ([7, 4, 4, 0], [9, 3, 3, 0]),                         # tie for second
    ([7, 4, 2, 2], [9, 4, 1, 1]),                         # tie for third
    ([5, 5, 2.5, 2.5], [6.5, 6.5, 1, 1]),                 # two pairs
    ([4, 4, 4, 3], [5, 5, 5, 0]),                         # 3-way first
    ([6, 3, 3, 3], [9, 2, 2, 2]),                         # 3-way second
    ([3.75] * 4, [3.75] * 4),                             # all tied
    ([0, 0, 0, 15], [2, 2, 2, 9]),                        # order independent
])
def test_rank_payouts(scores, expected):
    assert np.allclose(calculate_rank_payouts(scores), expected)


def test_rank_payouts_always_sum_to_15():
    rng = np.random.default_rng(1)
    for _ in range(2000):
        s = rng.integers(0, 4, size=4)  # small alphabet forces many ties
        assert calculate_rank_payouts(s).sum() == pytest.approx(15)


# --- four way --------------------------------------------------------------

def test_four_way_example_two_tied_first():
    # players 0 and 1 mirror each other, others are crushed
    res = score_four_way([[0, 0, 0, 50, 50], [0, 0, 0, 50, 50], [100, 0, 0, 0, 0], [0, 0, 100, 0, 0]])
    # castles 4,5 split between p0/p1 (4.5 each); castle 2 all tie at 0 (0.5 each);
    # castle 1 to p2; castle 3 to p3
    assert np.allclose(res["castle_points"], [5, 5, 1.5, 3.5])
    assert np.allclose(res["payouts"], [6.5, 6.5, 0, 2])


def test_four_way_all_identical():
    res = score_four_way([[20] * 5] * 4)
    assert np.allclose(res["castle_points"], 3.75)
    assert np.allclose(res["payouts"], 3.75)


def test_four_way_three_way_castle_tie():
    res = score_four_way([[0, 0, 0, 0, 100], [0, 0, 0, 0, 100], [0, 0, 0, 0, 100], [0, 0, 0, 100, 0]])
    # castle 5 split 3 ways (5/3 each), castle 4 to p3, castles 1-3 split 4 ways (1.5 each)
    assert np.allclose(res["castle_points"], [5 / 3 + 1.5] * 3 + [4 + 1.5])
    assert np.allclose(res["payouts"], [2, 2, 2, 9])


def test_four_way_conservation_random():
    rng = np.random.default_rng(2)
    for _ in range(2000):
        # coarse allocations (multiples of 20) force castle and rank ties
        groups = [rng.multinomial(5, np.ones(5) / 5) * 20 for _ in range(4)]
        res = score_four_way(groups)
        assert res["castle_points"].sum() == pytest.approx(15)
        assert res["payouts"].sum() == pytest.approx(15)


def test_four_way_rejects_wrong_group_size():
    with pytest.raises(ValueError):
        score_four_way([[20] * 5] * 3)
