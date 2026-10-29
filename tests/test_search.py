import numpy as np

from blotto.generators import generate
from blotto.optimize.best_response import g1_best_response_dp
from blotto.optimize.search import evolutionary, local_search, neighbors, random_search
from blotto.vectorized import as_alloc_array, g1_scores, g1_tables


def _setup():
    rng = np.random.default_rng(0)
    opps = np.concatenate([generate("proportional", rng, 500), generate("dirichlet", rng, 500)])
    table = g1_tables(opps)
    return rng, table, (lambda X: g1_scores(X, table)), g1_best_response_dp(table)[1]


def test_neighbors_valid():
    nb = neighbors(np.array([0, 10, 20, 30, 40]))
    as_alloc_array(nb)
    assert len(nb) > 0 and not np.any((nb == [0, 10, 20, 30, 40]).all(1))


def test_optimizers_never_beat_exact_optimum_and_get_close():
    rng, table, obj, opt = _setup()
    rs = random_search(obj, rng, 2000)
    ev = evolutionary(obj, rng, pop=100, generations=40)
    ls = local_search(obj, ev.top[:3])
    for res in (rs, ev, ls):
        as_alloc_array(res.top)
        assert res.best_score <= opt + 1e-9
        assert np.all(np.diff(res.scores) <= 1e-12)
        assert np.all(np.diff([h[1] for h in res.history]) >= -1e-12)  # best-so-far is monotone
    assert ls.best_score >= ev.best_score - 1e-12
    assert opt - ls.best_score < 0.05 * opt
