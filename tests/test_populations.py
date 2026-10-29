import numpy as np
import pytest

from blotto.populations import (SCENARIOS, adversary_pool_g1, build_pools, build_scenarios,
                                sample_population)
from blotto.vectorized import as_alloc_array


@pytest.fixture(scope="module")
def g1_pools():
    return build_pools("g1", np.random.default_rng(0), n_ref=800, selfplay_iters=6)


def test_pools_nonempty_and_valid(g1_pools):
    for name, pool in g1_pools.items():
        assert len(pool) > 0, name
        as_alloc_array(pool)


def test_scenarios_train_holdout_differ(g1_pools):
    pools = dict(g1_pools, adversary=adversary_pool_g1(np.array([[0, 10, 20, 30, 40]]), k=5))
    tr = build_scenarios("g1", pools, 500, 1, "train")
    ho = build_scenarios("g1", pools, 500, 1, "holdout")
    assert set(tr) == set(SCENARIOS)
    for name in tr:
        as_alloc_array(tr[name].allocs)
        assert len(tr[name]) == 500
        assert not np.array_equal(tr[name].allocs, ho[name].allocs)
    again = build_scenarios("g1", pools, 500, 1, "train")
    assert all(np.array_equal(tr[n].allocs, again[n].allocs) for n in tr)  # reproducible


def test_adversarial_skipped_without_pool(g1_pools):
    assert "adversarial" not in build_scenarios("g1", g1_pools, 100, 1, "train")


def test_mixture_weights_respected():
    pop = sample_population({"equal": 3, "uniform_random": 1}, 20_000, np.random.default_rng(1))
    assert abs(np.mean(pop.labels == "equal") - 0.75) < 0.02
