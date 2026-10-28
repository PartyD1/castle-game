"""Exact Game 1 best responses.

Because Game 1 scores are additive across castles, the best response to any
finite (or weighted) population is a knapsack problem solved exactly by DP,
and exhaustive enumeration of every allocation is cheap enough to list the
exact top-k as well.
"""
from __future__ import annotations

import numpy as np

from ..config import DEFAULT_GAME, GameConfig
from ..vectorized import all_allocations, g1_scores, g1_tables


def g1_best_response_dp(table: np.ndarray) -> tuple[np.ndarray, float]:
    """Exact optimum of sum_c table[c, x_c] subject to sum x = S, x >= 0 integer."""
    C, S1 = table.shape
    S = S1 - 1
    V = np.full(S + 1, -np.inf)
    V[0] = 0.0
    choice = np.zeros((C, S + 1), dtype=np.int64)
    a = np.arange(S + 1)
    s = a[:, None]
    for c in reversed(range(C)):
        rest = s - a[None, :]                                  # (s, a) -> soldiers left for later castles
        cand = np.where(rest >= 0, table[c][None, :] + V[np.clip(rest, 0, S)], -np.inf)
        choice[c] = cand.argmax(1)
        V = cand.max(1)
    alloc = np.zeros(C, dtype=np.int64)
    left = S
    for c in range(C):
        alloc[c] = choice[c, left]
        left -= alloc[c]
    return alloc, float(V[S])


def g1_top_k(table: np.ndarray, k: int = 10, cfg: GameConfig = DEFAULT_GAME) -> tuple[np.ndarray, np.ndarray]:
    """Exact top-k allocations by exhaustive enumeration (sorted best first)."""
    allocs = all_allocations(cfg)
    scores = g1_scores(allocs, table)
    idx = np.argpartition(-scores, min(k, len(scores) - 1))[:k]
    idx = idx[np.argsort(-scores[idx], kind="stable")]
    return allocs[idx].astype(np.int64), scores[idx]


def g1_best_response(opps: np.ndarray, cfg: GameConfig = DEFAULT_GAME, weights=None) -> tuple[np.ndarray, float]:
    return g1_best_response_dp(g1_tables(opps, cfg, weights))


def g1_near_optimal(table: np.ndarray, tol: float, cfg: GameConfig = DEFAULT_GAME, cap: int = 100_000):
    """All allocations within `tol` points of the exact optimum (up to `cap`, best first)."""
    allocs = all_allocations(cfg)
    scores = g1_scores(allocs, table)
    best = scores.max()
    idx = np.flatnonzero(scores >= best - tol)
    idx = idx[np.argsort(-scores[idx], kind="stable")][:cap]
    return allocs[idx].astype(np.int64), scores[idx]
