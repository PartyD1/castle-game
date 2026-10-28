"""Vectorized batch scoring for both games.

Game 1 is additively separable across castles: against a finite population,
a candidate's expected score is sum_c table[c, x_c] where table[c, a] is the
expected points from putting `a` soldiers on castle c.  That turns exact
evaluation of millions of candidates into table lookups.

Game 2 is evaluated against sampled opponent triples.  The same triples are
reused for every candidate (common random numbers) so candidate differences
are not swamped by sampling noise.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .config import DEFAULT_GAME, SCALE, GameConfig


def as_alloc_array(x, cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    """Validate a batch of allocations, returning an (n, C) int64 array."""
    arr = np.atleast_2d(np.asarray(x))
    if arr.ndim != 2 or arr.shape[1] != cfg.n_castles:
        raise ValueError(f"expected shape (n, {cfg.n_castles}), got {arr.shape}")
    if arr.dtype.kind == "f" and not np.all(arr == np.round(arr)):
        raise ValueError("allocations must be whole numbers")
    out = arr.astype(np.int64)
    if np.any(out < 0):
        raise ValueError("allocations must be nonnegative")
    bad = out.sum(1) != cfg.soldiers
    if np.any(bad):
        raise ValueError(f"{int(bad.sum())} allocation(s) do not sum to {cfg.soldiers}")
    return out


# --------------------------------------------------------------------------
# Game 1
# --------------------------------------------------------------------------

def g1_tables(opps: np.ndarray, cfg: GameConfig = DEFAULT_GAME, weights: np.ndarray | None = None) -> np.ndarray:
    """table[c, a] = expected castle-c points when placing `a` soldiers on c.

    `weights` optionally gives each opponent a probability mass (defaults to uniform).
    """
    n, C = opps.shape
    w = np.full(n, 1.0 / n) if weights is None else np.asarray(weights, float) / np.sum(weights)
    S = cfg.soldiers
    table = np.empty((C, S + 1))
    for c in range(C):
        eq = np.bincount(opps[:, c], weights=w, minlength=S + 1)[: S + 1]
        less = np.concatenate([[0.0], np.cumsum(eq)[:-1]])
        table[c] = cfg.values[c] * (less + 0.5 * eq)
    return table


def g1_scores(cands: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Exact expected points of each candidate against the population behind `table`."""
    cands = np.atleast_2d(cands)
    return table[np.arange(table.shape[0]), cands].sum(1)


def g1_matrix(A: np.ndarray, B: np.ndarray, cfg: GameConfig = DEFAULT_GAME, chunk: int = 2048) -> np.ndarray:
    """M[i, j] = points allocation A[i] scores against B[j] (head to head)."""
    v = cfg.values_arr.astype(float)
    out = np.empty((len(A), len(B)))
    for s in range(0, len(A), chunk):
        a = A[s:s + chunk, None, :]
        b = B[None, :, :]
        out[s:s + chunk] = ((a > b) * v + (a == b) * (v / 2)).sum(-1)
    return out


def g1_castle_stats(cand: np.ndarray, opps: np.ndarray) -> dict:
    """Per-castle win/tie/loss rates and matchup W/L/T frequencies for one candidate."""
    cand = np.asarray(cand)
    win = (cand[None] > opps).mean(0)
    tie = (cand[None] == opps).mean(0)
    return {"castle_win": win, "castle_tie": tie, "castle_loss": 1 - win - tie}


def g1_matchup_outcomes(cand: np.ndarray, opps: np.ndarray, cfg: GameConfig = DEFAULT_GAME) -> dict:
    pts = g1_matrix(np.atleast_2d(cand), opps, cfg)[0]
    half = cfg.total_points / 2
    return {"win": float(np.mean(pts > half)), "tie": float(np.mean(pts == half)),
            "loss": float(np.mean(pts < half))}


@lru_cache(maxsize=8)
def _compositions(S: int, C: int) -> np.ndarray:
    if C == 1:
        return np.array([[S]], dtype=np.int16)
    blocks = []
    for first in range(S + 1):
        rest = _compositions(S - first, C - 1)
        blk = np.empty((len(rest), C), dtype=np.int16)
        blk[:, 0] = first
        blk[:, 1:] = rest
        blocks.append(blk)
    return np.concatenate(blocks)


def all_allocations(cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    """Every valid allocation (C(S+C-1, C-1) rows; 4,598,126 for the default rules)."""
    out = _compositions(cfg.soldiers, cfg.n_castles)
    out.flags.writeable = False
    return out


# --------------------------------------------------------------------------
# Game 2
# --------------------------------------------------------------------------

def _share_table(cfg: GameConfig) -> np.ndarray:
    """share[k, c] = SCALE * v_c / k for k = 1..4 (row 0 unused)."""
    v12 = SCALE * cfg.values_arr
    share = np.zeros((5, cfg.n_castles), dtype=np.int64)
    for k in range(1, 5):
        share[k] = v12 // k
    return share


def _rank_payout(own: np.ndarray, others: np.ndarray, cum: np.ndarray):
    """Payout and (h, e) for `own` scores (...,) against `others` (..., 3)."""
    h = (others > own[..., None]).sum(-1)
    e = 1 + (others == own[..., None]).sum(-1)
    return (cum[h + e] - cum[h]) / e, h, e


def g2_play(groups: np.ndarray, cfg: GameConfig = DEFAULT_GAME) -> tuple[np.ndarray, np.ndarray]:
    """Score arbitrary groups (G, 4, C). Returns (castle points, payouts), each (G, 4)."""
    groups = np.asarray(groups)
    top = groups.max(1, keepdims=True)
    at_max = groups == top
    k = at_max.sum(1)  # (G, C)
    share = _share_table(cfg)
    per_castle = share[k, np.arange(cfg.n_castles)]  # (G, C)
    pts = (at_max * per_castle[:, None, :]).sum(-1)  # (G, 4) scaled ints
    cum = cfg.cum_payouts
    pay = np.empty(pts.shape)
    for i in range(4):
        others = np.delete(pts, i, axis=1)
        pay[:, i], _, _ = _rank_payout(pts[:, i], others, cum)
    return pts / SCALE, pay


def sample_triples(rng: np.random.Generator, n_pop: int, k: int) -> np.ndarray:
    """k rows of 3 distinct opponent indices drawn uniformly from range(n_pop)."""
    if n_pop < 3:
        raise ValueError("need at least 3 opponents to form a group")
    t = rng.integers(0, n_pop, size=(k, 3))
    while True:
        bad = (t[:, 0] == t[:, 1]) | (t[:, 0] == t[:, 2]) | (t[:, 1] == t[:, 2])
        if not bad.any():
            return t
        t[bad] = rng.integers(0, n_pop, size=(int(bad.sum()), 3))


class G2Field:
    """Pre-processed opponent triples, reusable across many candidates (CRN)."""

    def __init__(self, opp_groups: np.ndarray, cfg: GameConfig = DEFAULT_GAME):
        self.cfg = cfg
        self.groups = np.asarray(opp_groups, dtype=np.int16)        # (K, 3, C)
        self.m = self.groups.max(1)                                  # (K, C)
        self.at_max = self.groups == self.m[:, None, :]             # (K, 3, C)
        self.t = self.at_max.sum(1)                                  # (K, C)
        share = _share_table(cfg)
        cidx = np.arange(cfg.n_castles)
        self.share_t = share[self.t, cidx].astype(np.int32)          # opp share if they win alone among opps
        self.share_t1 = share[self.t + 1, cidx].astype(np.int32)     # share when candidate also ties
        self.v12 = (SCALE * cfg.values_arr).astype(np.int32)
        self.cum = cfg.cum_payouts

    @classmethod
    def from_population(cls, opps: np.ndarray, rng: np.random.Generator, k: int,
                        cfg: GameConfig = DEFAULT_GAME) -> "G2Field":
        return cls(opps[sample_triples(rng, len(opps), k)], cfg)

    @property
    def size(self) -> int:
        return len(self.groups)

    def _batch(self, X: np.ndarray):
        Xb = X[:, None, :]
        win = Xb > self.m[None]
        tie = Xb == self.m[None]
        cand = np.where(win, self.v12, np.where(tie, self.share_t1[None], 0)).sum(-1)
        opp_share = np.where(win, 0, np.where(tie, self.share_t1[None], self.share_t[None]))
        opp = (self.at_max[None] * opp_share[:, :, None, :]).sum(-1)
        pay, h, e = _rank_payout(cand, opp, self.cum)
        return cand, pay, h, e, win, tie

    def payout_samples(self, X: np.ndarray, max_cells: int = 1_000_000) -> np.ndarray:
        """Per-group payouts (B, K) for each candidate; used for paired comparisons."""
        X = np.atleast_2d(X)
        bs = max(1, max_cells // self.size)
        return np.concatenate([self._batch(X[s:s + bs])[1] for s in range(0, len(X), bs)])

    def mean_payout(self, X: np.ndarray, max_cells: int = 1_000_000) -> np.ndarray:
        X = np.atleast_2d(X)
        bs = max(1, max_cells // self.size)
        return np.concatenate([self._batch(X[s:s + bs])[1].mean(1) for s in range(0, len(X), bs)])

    def evaluate(self, X: np.ndarray, max_cells: int = 1_000_000) -> dict:
        """Mean payout with standard error, placement probabilities and castle stats."""
        X = np.atleast_2d(X)
        bs = max(1, max_cells // self.size)
        keys = ("mean", "se", "pos", "castle_points", "castle_win", "castle_tie")
        acc = {k: [] for k in keys}
        for s in range(0, len(X), bs):
            cand, pay, h, e, win, tie = self._batch(X[s:s + bs])
            acc["mean"].append(pay.mean(1))
            acc["se"].append(pay.std(1, ddof=1) / np.sqrt(self.size))
            # tied players share the ranks they occupy: rank r gets 1/e if h <= r < h+e
            r = np.arange(4)[None, None, :]
            occ = (r >= h[..., None]) & (r < (h + e)[..., None])
            acc["pos"].append((occ / e[..., None]).mean(1))
            acc["castle_points"].append(cand.mean(1) / SCALE)
            acc["castle_win"].append(win.mean(1))
            acc["castle_tie"].append(tie.mean(1))
        return {k: np.concatenate(v) for k, v in acc.items()}
