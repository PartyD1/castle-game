"""Self-play via fictitious play.

Each iteration computes a best response to the current field: an `anchor`
share of the starting population plus a uniform mixture over every best
response found so far.  The trajectory reveals whether responses converge to
one allocation, cycle among several, or keep wandering.
"""
from __future__ import annotations

import numpy as np

from ..config import DEFAULT_GAME, GameConfig
from ..vectorized import g1_scores, g1_tables
from .best_response import g1_best_response_dp, g2_best_response


def _summarize(brs: list[np.ndarray], values: list[float]) -> dict:
    B = np.array(brs)
    l1 = [0] + [int(np.abs(B[i] - B[i - 1]).sum()) for i in range(1, len(B))]
    first_seen = {}
    revisits = 0
    for i, b in enumerate(map(tuple, B)):
        if b in first_seen:
            revisits += 1
        first_seen.setdefault(b, i)
    tail = B[len(B) // 2:]
    distinct_tail = len({tuple(b) for b in tail})
    if len(tail) and distinct_tail == 1:
        verdict = "converged"
    elif revisits and distinct_tail <= max(2, len(tail) // 3):
        verdict = "cycling"
    else:
        verdict = "wandering (no fixed point within the iteration budget)"
    return {"best_responses": B.tolist(), "br_value": values, "l1_step": l1,
            "distinct": len(first_seen), "revisits": revisits,
            "distinct_in_second_half": distinct_tail, "verdict": verdict}


def g1_fictitious_play(init_pop: np.ndarray, iters: int = 40, anchor: float = 0.5,
                       cfg: GameConfig = DEFAULT_GAME) -> dict:
    base = g1_tables(init_pop, cfg)
    brs, values = [], []
    for t in range(iters):
        if brs:
            hist_table = g1_tables(np.array(brs), cfg)
            table = anchor * base + (1 - anchor) * hist_table
        else:
            table = base
        br, val = g1_best_response_dp(table)
        brs.append(br)
        values.append(val)
    out = _summarize(brs, values)
    # how the final empirical BR mixture itself fares vs the starting population
    final_mix = np.array(brs)
    out["mix_vs_init"] = float(g1_scores(final_mix, base).mean())
    return out


def g2_fictitious_play(init_pop: np.ndarray, rng: np.random.Generator, iters: int = 12, anchor: float = 0.5,
                       field_size: int = 4000, groups: int = 4000, cfg: GameConfig = DEFAULT_GAME,
                       **br_kwargs) -> dict:
    brs, values = [], []
    for t in range(iters):
        n_hist = 0 if not brs else int(round(field_size * (1 - anchor)))
        idx = rng.integers(0, len(init_pop), field_size - n_hist)
        parts = [init_pop[idx]]
        if n_hist:
            H = np.array(brs)
            parts.append(H[rng.integers(0, len(H), n_hist)])
        field = np.concatenate(parts)
        init = np.array(brs[-3:]) if brs else None
        res = g2_best_response(field, rng, cfg, groups=groups, init=init, **br_kwargs)
        brs.append(res.best)
        values.append(res.best_score)
    return _summarize(brs, values)
