"""Generic optimizers over valid allocations.

All optimizers take `objective(X: (n, C) int) -> (n,) scores` (higher is
better), so they work for exact Game 1 tables and for Game 2 CRN fields.
Each returns a SearchResult with the top unique allocations and a
best-so-far history for convergence plots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..config import DEFAULT_GAME, GameConfig
from ..generators import generate, jitter, to_alloc

Objective = Callable[[np.ndarray], np.ndarray]


@dataclass
class SearchResult:
    method: str
    top: np.ndarray            # (k, C) best unique allocations, best first
    scores: np.ndarray         # (k,)
    history: list = field(default_factory=list)  # best-so-far after each step: (evals, score)
    evaluations: int = 0

    @property
    def best(self) -> np.ndarray:
        return self.top[0]

    @property
    def best_score(self) -> float:
        return float(self.scores[0])


def _unique_top(X: np.ndarray, s: np.ndarray, k: int):
    X, idx = np.unique(X, axis=0, return_index=True)
    s = s[idx]
    order = np.argsort(-s, kind="stable")[:k]
    return X[order], s[order]


def _merge(top, scores, X, s, k):
    return _unique_top(np.concatenate([top, X]), np.concatenate([scores, s]), k)


def random_candidates(rng: np.random.Generator, n: int, cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    """Diverse random candidates: half uniform over the simplex, half sparse/structured."""
    parts = [generate("uniform_random", rng, n // 2, cfg),
             generate("dirichlet", rng, n // 4, cfg, alphas=(0.3, 0.7, 1.5)),
             generate("noisy_heuristic", rng, n - n // 2 - n // 4, cfg, max_moves=25)]
    return np.concatenate(parts)


def random_search(objective: Objective, rng: np.random.Generator, n: int, cfg: GameConfig = DEFAULT_GAME,
                  k: int = 50, batch: int = 1000) -> SearchResult:
    top = np.zeros((0, cfg.n_castles), dtype=np.int64)
    scores = np.zeros(0)
    hist, evals = [], 0
    X_all = random_candidates(rng, n, cfg)
    for s in range(0, n, batch):
        X = X_all[s:s + batch]
        top, scores = _merge(top, scores, X, objective(X), k)
        evals += len(X)
        hist.append((evals, float(scores[0])))
    return SearchResult("random", top, scores, hist, evals)


def crossover(rng, A, B, S):
    """Blend two parents castle-wise (random convex weights), then repair to S."""
    t = rng.random((len(A), 1))
    mix = np.where(rng.random(A.shape) < 0.5, A, B)
    w = np.where(rng.random((len(A), 1)) < 0.5, mix, t * A + (1 - t) * B)
    return to_alloc(w + 1e-9, S)


def mutate(rng, X, max_chunk=10, p_big=0.3):
    """Move soldiers: many single-soldier moves plus occasional large transfers."""
    out = jitter(X, rng, rng.integers(0, 6, len(X)))
    big = rng.random(len(X)) < p_big
    if big.any():
        rows = np.flatnonzero(big)
        C = X.shape[1]
        src = rng.integers(0, C, len(rows))
        dst = rng.integers(0, C, len(rows))
        amt = np.minimum(out[rows, src], rng.integers(1, max_chunk + 1, len(rows)))
        out[rows, src] -= amt
        out[rows, dst] += amt
    return out


def evolutionary(objective: Objective, rng: np.random.Generator, cfg: GameConfig = DEFAULT_GAME,
                 pop: int = 200, generations: int = 60, elite_frac: float = 0.2, k: int = 50,
                 init: np.ndarray | None = None, patience: int = 15) -> SearchResult:
    S = cfg.soldiers
    P = random_candidates(rng, pop, cfg)
    if init is not None and len(init):
        P[: min(len(init), pop // 2)] = init[: pop // 2]
    f = objective(P)
    evals = len(P)
    top, scores = _unique_top(P, f, k)
    hist = [(evals, float(scores[0]))]
    n_elite = max(2, int(pop * elite_frac))
    stale = 0
    for _ in range(generations):
        order = np.argsort(-f)
        elite, ef = P[order[:n_elite]], f[order[:n_elite]]
        # tournament selection of parents from the whole population
        a = rng.integers(0, pop, (pop - n_elite, 2))
        pa = P[np.where(f[a[:, 0]] >= f[a[:, 1]], a[:, 0], a[:, 1])]
        b = rng.integers(0, pop, (pop - n_elite, 2))
        pb = P[np.where(f[b[:, 0]] >= f[b[:, 1]], b[:, 0], b[:, 1])]
        kids = mutate(rng, crossover(rng, pa, pb, S))
        kf = objective(kids)
        evals += len(kids)
        P = np.concatenate([elite, kids])
        f = np.concatenate([ef, kf])
        prev = scores[0]
        top, scores = _merge(top, scores, kids, kf, k)
        hist.append((evals, float(scores[0])))
        stale = stale + 1 if scores[0] <= prev + 1e-12 else 0
        if stale >= patience:
            break
    return SearchResult("evolutionary", top, scores, hist, evals)


def neighbors(x: np.ndarray, steps=(1, 2, 3, 5, 10)) -> np.ndarray:
    """All allocations reachable by moving `d` soldiers from one castle to another."""
    C = len(x)
    out = []
    for d in steps:
        for i in range(C):
            if x[i] < d:
                continue
            for j in range(C):
                if i != j:
                    y = x.copy()
                    y[i] -= d
                    y[j] += d
                    out.append(y)
    return np.array(out, dtype=np.int64).reshape(-1, C)


def local_search(objective: Objective, starts: np.ndarray, cfg: GameConfig = DEFAULT_GAME,
                 max_iter: int = 200, k: int = 50, steps=(1, 2, 3, 5, 10)) -> SearchResult:
    """Steepest-ascent hill climbing from each start; returns the union of local optima."""
    starts = np.atleast_2d(starts).astype(np.int64)
    s0 = objective(starts)
    evals = len(starts)
    top, scores = _unique_top(starts, s0, k)
    hist = [(evals, float(scores[0]))]
    for x, fx in zip(starts, s0):
        for _ in range(max_iter):
            nb = neighbors(x, steps)
            fn = objective(nb)
            evals += len(nb)
            top, scores = _merge(top, scores, nb, fn, k)
            j = int(np.argmax(fn))
            if fn[j] <= fx + 1e-12:
                break
            x, fx = nb[j], fn[j]
        hist.append((evals, float(scores[0])))
    return SearchResult("local", top, scores, hist, evals)
