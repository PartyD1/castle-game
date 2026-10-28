"""Exact scalar reference scoring.

These functions favour clarity over speed; `vectorized.py` must agree with
them exactly (enforced by tests).
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .config import DEFAULT_GAME, SCALE, GameConfig


def validate_allocation(alloc: Sequence, cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    """Return the allocation as an int array, or raise ValueError explaining why it is invalid."""
    arr = np.asarray(alloc)
    if arr.ndim != 1 or arr.shape[0] != cfg.n_castles:
        raise ValueError(f"allocation must have exactly {cfg.n_castles} entries, got shape {arr.shape}")
    if arr.dtype.kind == "b":
        raise ValueError("allocation entries must be integers, not booleans")
    if arr.dtype.kind not in "iuf":
        raise ValueError("allocation entries must be numeric")
    if arr.dtype.kind == "f":
        if not np.all(np.isfinite(arr)) or not np.all(arr == np.round(arr)):
            raise ValueError("allocation entries must be whole numbers")
    out = arr.astype(np.int64)
    if np.any(out < 0):
        raise ValueError("allocation entries must be nonnegative")
    if int(out.sum()) != cfg.soldiers:
        raise ValueError(f"allocation must sum to {cfg.soldiers}, got {int(out.sum())}")
    return out


def score_head_to_head(a: Sequence, b: Sequence, cfg: GameConfig = DEFAULT_GAME) -> tuple[float, float]:
    """Castle points (a, b) for one head-to-head matchup. Ties split the castle."""
    a = validate_allocation(a, cfg)
    b = validate_allocation(b, cfg)
    pa = pb = 0.0
    for v, x, y in zip(cfg.values, a, b):
        if x > y:
            pa += v
        elif y > x:
            pb += v
        else:
            pa += v / 2
            pb += v / 2
    return pa, pb


def calculate_rank_payouts(scores: Sequence[float], payouts: Sequence[float] = DEFAULT_GAME.payouts,
                           tol: float = 1e-9) -> np.ndarray:
    """Placement payouts with tied players splitting the payouts of the ranks they occupy.

    A player with h strictly-better players and e tied players (including itself)
    occupies ranks h..h+e-1 and receives the mean of those payouts.
    """
    s = np.asarray(scores, dtype=float)
    n = len(s)
    pay = np.zeros(n, dtype=float)
    pay[: min(n, len(payouts))] = np.asarray(payouts, dtype=float)[:n]
    cum = np.concatenate([[0.0], np.cumsum(pay)])
    out = np.empty(n)
    for i in range(n):
        h = int(np.sum(s > s[i] + tol))
        e = int(np.sum(np.abs(s - s[i]) <= tol))
        out[i] = (cum[h + e] - cum[h]) / e
    return out


def four_way_castle_points_scaled(allocs: np.ndarray, cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    """Castle points for each player multiplied by SCALE (exact integers)."""
    n_players = allocs.shape[0]
    pts = np.zeros(n_players, dtype=np.int64)
    for c, v in enumerate(cfg.values):
        col = allocs[:, c]
        top = col.max()
        winners = np.flatnonzero(col == top)
        share = SCALE * v // len(winners)
        pts[winners] += share
    return pts


def score_four_way(allocs: Sequence[Sequence], cfg: GameConfig = DEFAULT_GAME) -> dict:
    """Score one four-player group.

    Returns castle points and placement payouts for each of the 4 players.
    """
    arr = np.stack([validate_allocation(a, cfg) for a in allocs])
    if arr.shape[0] != 4:
        raise ValueError("four-way battle needs exactly 4 allocations")
    scaled = four_way_castle_points_scaled(arr, cfg)
    payouts = calculate_rank_payouts(scaled.astype(float), cfg.payouts, tol=0.5)
    return {"castle_points": scaled / SCALE, "payouts": payouts}
