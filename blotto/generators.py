"""Opponent strategy families.

Every generator has the signature `gen(rng, n, cfg, **params) -> (n, C) int64`
and every row is a valid allocation (nonnegative, sums to cfg.soldiers).
Templates below are expressed as castle weights, so they scale to any
soldier total; for non-default castle counts the template families fall back
to value-based weights.

The `strategic`, `best_response` and `self_play` families draw from pools of
computed allocations supplied by the caller (see populations.build_pools).
"""
from __future__ import annotations

import numpy as np

from .config import DEFAULT_GAME, GameConfig


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def to_alloc(w: np.ndarray, S: int) -> np.ndarray:
    """Scale nonnegative weights to integers summing to S (largest remainder rounding)."""
    w = np.atleast_2d(np.asarray(w, dtype=float))
    w = np.clip(w, 0, None)
    tot = w.sum(1, keepdims=True)
    w = np.where(tot > 0, w, 1.0)
    x = w / w.sum(1, keepdims=True) * S
    base = np.floor(x).astype(np.int64)
    short = S - base.sum(1)
    order = np.argsort(-(x - base), axis=1, kind="stable")
    rank = np.argsort(order, axis=1)
    base += rank < short[:, None]
    return base


def jitter(allocs: np.ndarray, rng: np.random.Generator, moves: np.ndarray | int) -> np.ndarray:
    """Move single soldiers between random castles; `moves` per row (array or int)."""
    out = allocs.copy()
    n, C = out.shape
    moves = np.broadcast_to(np.asarray(moves), (n,)).astype(np.int64)
    rows = np.arange(n)
    for step in range(int(moves.max(initial=0))):
        active = moves > step
        src = rng.integers(0, C, n)
        dst = rng.integers(0, C, n)
        ok = active & (out[rows, src] > 0)
        out[rows[ok], src[ok]] -= 1
        out[rows[ok], dst[ok]] += 1
    return out


def round_to(allocs: np.ndarray, step: int, S: int) -> np.ndarray:
    """Round to multiples of `step` while keeping the total (requires S % step == 0)."""
    if S % step:
        return allocs
    return to_alloc(allocs / step + 1e-9, S // step) * step


def _templates(rng, n, cfg, templates, noise):
    T = np.asarray(templates, dtype=float)
    if T.shape[1] != cfg.n_castles:
        T = cfg.values_arr[None, :].astype(float)
    w = T[rng.integers(0, len(T), n)]
    sig = rng.uniform(0, noise, (n, 1))
    w = w * np.exp(rng.normal(0, 1, w.shape) * sig)
    return to_alloc(w, cfg.soldiers)


# --------------------------------------------------------------------------
# families
# --------------------------------------------------------------------------

def equal(rng, n, cfg=DEFAULT_GAME, noise=0.15, exact_frac=0.3):
    w = np.ones((n, cfg.n_castles)) * np.exp(rng.normal(0, 1, (n, cfg.n_castles)) * rng.uniform(0, noise, (n, 1)))
    w[rng.random(n) < exact_frac] = 1.0
    return to_alloc(w, cfg.soldiers)


def proportional(rng, n, cfg=DEFAULT_GAME, power=(0.6, 1.6), noise=0.15, exact_frac=0.3):
    p = rng.uniform(*power, (n, 1))
    p[rng.random(n) < exact_frac] = 1.0
    w = cfg.values_arr[None, :].astype(float) ** p
    w = w * np.exp(rng.normal(0, 1, w.shape) * rng.uniform(0, noise, (n, 1)))
    return to_alloc(w, cfg.soldiers)


HIGH_TEMPLATES = [[0, 0, 0, 50, 50], [0, 0, 0, 45, 55], [0, 0, 20, 35, 45], [0, 0, 30, 30, 40],
                  [0, 0, 0, 40, 60], [0, 0, 0, 0, 100], [0, 5, 15, 35, 45], [0, 0, 25, 35, 40],
                  [5, 5, 10, 35, 45], [0, 10, 10, 30, 50]]
MIDDLE_TEMPLATES = [[0, 30, 35, 35, 0], [0, 25, 35, 40, 0], [10, 20, 35, 35, 0], [0, 0, 50, 50, 0],
                    [5, 20, 30, 30, 15], [0, 33, 33, 34, 0], [0, 20, 40, 40, 0], [10, 25, 30, 25, 10]]
LOW_TEMPLATES = [[20, 30, 50, 0, 0], [15, 25, 30, 30, 0], [10, 20, 30, 40, 0], [25, 25, 25, 25, 0],
                 [30, 35, 35, 0, 0], [0, 30, 30, 40, 0], [12, 22, 33, 33, 0], [5, 25, 30, 40, 0]]
HEURISTICS = [[20, 20, 20, 20, 20], [7, 13, 20, 27, 33], [10, 15, 20, 25, 30], [0, 10, 20, 30, 40],
              [5, 10, 20, 30, 35], [0, 0, 20, 35, 45], [0, 15, 25, 25, 35], [10, 10, 20, 30, 30],
              [0, 0, 33, 33, 34], [5, 15, 20, 25, 35], [0, 20, 20, 30, 30], [2, 8, 20, 30, 40],
              [0, 0, 0, 50, 50], [0, 25, 25, 25, 25], [1, 4, 15, 35, 45], [10, 10, 10, 35, 35]]


def high_value(rng, n, cfg=DEFAULT_GAME, noise=0.25):
    return _templates(rng, n, cfg, HIGH_TEMPLATES, noise)


def middle(rng, n, cfg=DEFAULT_GAME, noise=0.25):
    return _templates(rng, n, cfg, MIDDLE_TEMPLATES, noise)


def low_value(rng, n, cfg=DEFAULT_GAME, noise=0.25):
    return _templates(rng, n, cfg, LOW_TEMPLATES, noise)


def uniform_random(rng, n, cfg=DEFAULT_GAME):
    """Uniform over all valid integer allocations (stars and bars)."""
    S, C = cfg.soldiers, cfg.n_castles
    bars = np.sort(np.argsort(rng.random((n, S + C - 1)), axis=1)[:, : C - 1], axis=1)
    edges = np.concatenate([np.full((n, 1), -1), bars, np.full((n, 1), S + C - 1)], axis=1)
    return (np.diff(edges, axis=1) - 1).astype(np.int64)


def dirichlet(rng, n, cfg=DEFAULT_GAME, alphas=(0.3, 1.0, 3.0, 10.0), value_weighted_frac=0.5):
    a = np.asarray(alphas, dtype=float)[rng.integers(0, len(alphas), n)][:, None]
    base = np.ones((n, cfg.n_castles))
    vw = rng.random(n) < value_weighted_frac
    base[vw] = cfg.values_arr / cfg.values_arr.mean()
    alpha = np.maximum(a * base, 1e-3)
    g = rng.gamma(alpha)
    return to_alloc(g, cfg.soldiers)


def noisy_heuristic(rng, n, cfg=DEFAULT_GAME, max_moves=15):
    base = _templates(rng, n, cfg, HEURISTICS, 0.0)
    return jitter(base, rng, rng.integers(0, max_moves + 1, n))


def rounded(rng, n, cfg=DEFAULT_GAME, steps=(5, 10)):
    src = np.concatenate([noisy_heuristic(rng, n, cfg), dirichlet(rng, n, cfg, alphas=(1.0, 3.0))])
    src = src[rng.permutation(len(src))[:n]]
    step = np.asarray(steps)[rng.integers(0, len(steps), n)]
    out = src.copy()
    for s in np.unique(step):
        m = step == s
        out[m] = round_to(src[m], int(s), cfg.soldiers)
    return out


def from_pool(rng, n, cfg=DEFAULT_GAME, pool=None, max_moves=3):
    """Sample computed allocations with light noise (players rarely copy exactly)."""
    if pool is None or len(pool) == 0:
        raise ValueError("this family needs a non-empty pool of computed allocations")
    pool = np.asarray(pool, dtype=np.int64)
    base = pool[rng.integers(0, len(pool), n)]
    return jitter(base, rng, rng.integers(0, max_moves + 1, n))


FAMILIES = {
    "equal": equal,
    "proportional": proportional,
    "high_value": high_value,
    "middle": middle,
    "low_value": low_value,
    "uniform_random": uniform_random,
    "dirichlet": dirichlet,
    "noisy_heuristic": noisy_heuristic,
    "rounded": rounded,
    "strategic": from_pool,
    "best_response": from_pool,
    "self_play": from_pool,
}
POOL_FAMILIES = ("strategic", "best_response", "self_play")
NAIVE_FAMILIES = tuple(f for f in FAMILIES if f not in POOL_FAMILIES)


def generate(family: str, rng: np.random.Generator, n: int, cfg: GameConfig = DEFAULT_GAME, **params) -> np.ndarray:
    if family not in FAMILIES:
        raise KeyError(f"unknown family {family!r}; choose from {sorted(FAMILIES)}")
    if n <= 0:
        return np.zeros((0, cfg.n_castles), dtype=np.int64)
    return FAMILIES[family](rng, n, cfg, **params)
