import numpy as np
import pytest

from blotto.config import GameConfig
from blotto.generators import FAMILIES, NAIVE_FAMILIES, generate, jitter, round_to, to_alloc
from blotto.vectorized import as_alloc_array

POOL = np.array([[0, 10, 20, 30, 40], [3, 5, 22, 32, 38]])


@pytest.mark.parametrize("family", list(FAMILIES))
@pytest.mark.parametrize("cfg", [GameConfig(), GameConfig(values=(2, 3, 5, 7, 11), soldiers=60)])
def test_every_family_valid(family, cfg):
    rng = np.random.default_rng(0)
    params = {"pool": to_alloc(POOL, cfg.soldiers)} if family not in NAIVE_FAMILIES else {}
    out = generate(family, rng, 3000, cfg, **params)
    as_alloc_array(out, cfg)  # raises if any row is invalid
    assert out.shape == (3000, 5)


@pytest.mark.parametrize("family", [f for f in NAIVE_FAMILIES if f != "equal"])
def test_families_have_variation(family):
    out = generate(family, np.random.default_rng(1), 2000)
    assert len(np.unique(out, axis=0)) > 50


def test_to_alloc_largest_remainder():
    assert to_alloc([[1, 2, 3, 4, 5]], 100).tolist() == [[7, 13, 20, 27, 33]]
    assert to_alloc([[0, 0, 0, 0, 0]], 100).tolist() == [[20, 20, 20, 20, 20]]


def test_jitter_and_round_preserve_total():
    rng = np.random.default_rng(2)
    base = generate("dirichlet", rng, 1000)
    j = jitter(base, rng, 40)
    assert np.all(j.sum(1) == 100) and np.all(j >= 0)
    r = round_to(base, 10, 100)
    assert np.all(r.sum(1) == 100) and np.all(r % 10 == 0)


def test_uniform_random_is_roughly_uniform():
    out = generate("uniform_random", np.random.default_rng(3), 50_000)
    # the marginal of one castle under uniform compositions has mean S/C = 20
    assert abs(out.mean() - 20) < 0.3
    assert out.max() > 70  # extreme allocations appear


def test_pool_family_requires_pool():
    with pytest.raises(ValueError):
        generate("strategic", np.random.default_rng(0), 10)
