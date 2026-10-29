"""Evaluation: tournaments, per-family breakdowns, confidence intervals, robustness."""
from __future__ import annotations

from itertools import combinations

import numpy as np

from .config import DEFAULT_GAME, GameConfig
from .populations import Population
from .vectorized import G2Field, g1_castle_stats, g1_matrix, g1_scores, g1_tables, g2_play

BASELINES: dict[str, list[int]] = {
    "equal": [20, 20, 20, 20, 20],
    "proportional": [7, 13, 20, 27, 33],
    "linear_10_30": [10, 15, 20, 25, 30],
    "linear_0_40": [0, 10, 20, 30, 40],
    "prop_skew": [5, 10, 20, 30, 35],
    "top3_heavy": [0, 0, 20, 35, 45],
    "top2_split": [0, 0, 0, 50, 50],
    "top3_even": [0, 0, 33, 33, 34],
    "skip_c1": [0, 25, 25, 25, 25],
    "top3_30_30_40": [0, 0, 30, 30, 40],
    "prop_rounded": [2, 8, 20, 30, 40],
    "high_tail": [1, 4, 15, 35, 45],
    "mid_high": [0, 15, 25, 25, 35],
    "low_floor": [10, 10, 10, 35, 35],
    "skip_c1_tilt": [0, 20, 20, 30, 30],
    "skip_c5": [25, 25, 25, 25, 0],
    "low_three": [20, 30, 50, 0, 0],
    "middle_three": [0, 30, 35, 35, 0],
    "all_c5": [0, 0, 0, 0, 100],
    "all_c1": [100, 0, 0, 0, 0],
    "c345_odd": [3, 3, 24, 32, 38],
    "c3_c5": [0, 0, 34, 0, 66],
    "c345_min": [1, 1, 32, 33, 33],
    "tilted_high": [11, 11, 11, 33, 34],
    "prop_plus1": [4, 6, 21, 31, 38],
}


def baseline_array() -> tuple[list[str], np.ndarray]:
    return list(BASELINES), np.array(list(BASELINES.values()), dtype=np.int64)


# --------------------------------------------------------------------------
# Game 1
# --------------------------------------------------------------------------

def g1_detail(cand: np.ndarray, pop: Population, cfg: GameConfig = DEFAULT_GAME) -> dict:
    pts = g1_matrix(np.atleast_2d(cand), pop.allocs, cfg)[0]
    half = cfg.total_points / 2
    stats = g1_castle_stats(cand, pop.allocs)
    fam = {f: float(pts[pop.labels == f].mean()) for f in np.unique(pop.labels)}
    return {"mean": float(pts.mean()), "win": float(np.mean(pts > half)), "tie": float(np.mean(pts == half)),
            "loss": float(np.mean(pts < half)), "castle_win": stats["castle_win"].tolist(),
            "castle_tie": stats["castle_tie"].tolist(), "by_family": fam}


def g1_round_robin(names: list[str], X: np.ndarray, cfg: GameConfig = DEFAULT_GAME) -> dict:
    """Every allocation against every other (self-matchups excluded)."""
    M = g1_matrix(X, X, cfg)
    np.fill_diagonal(M, np.nan)
    half = cfg.total_points / 2
    off = ~np.eye(len(X), dtype=bool)
    rows = []
    for i, n in enumerate(names):
        r = M[i][off[i]]
        st = g1_castle_stats(X[i], X[off[i]])
        rows.append({"name": n, "alloc": X[i].tolist(), "mean": float(r.mean()),
                     "win": float(np.mean(r > half)), "tie": float(np.mean(r == half)),
                     "loss": float(np.mean(r < half)), "castle_win": st["castle_win"].tolist(),
                     "castle_tie": st["castle_tie"].tolist()})
    return {"matrix": np.nan_to_num(M, nan=half).tolist(), "rows": rows}


# --------------------------------------------------------------------------
# Game 2
# --------------------------------------------------------------------------

def g2_round_robin(names: list[str], X: np.ndarray, cfg: GameConfig = DEFAULT_GAME) -> dict:
    """Exact: each allocation against every unordered triple of the other baselines."""
    n = len(X)
    rows = []
    for i in range(n):
        others = [j for j in range(n) if j != i]
        tri = np.array(list(combinations(others, 3)))
        field = G2Field(X[tri], cfg)
        ev = field.evaluate(X[i][None])
        rows.append({"name": names[i], "alloc": X[i].tolist(), "mean": float(ev["mean"][0]),
                     "pos": ev["pos"][0].tolist(), "castle_points": float(ev["castle_points"][0]),
                     "castle_win": ev["castle_win"][0].tolist(), "castle_tie": ev["castle_tie"][0].tolist(),
                     "groups": len(tri)})
    # conservation check over all groups of the baseline set
    groups = X[np.array(list(combinations(range(n), 4)))]
    pts, pay = g2_play(groups, cfg)
    assert np.allclose(pts.sum(1), cfg.total_points) and np.allclose(pay.sum(1), cfg.total_payout)
    return {"rows": rows, "n_groups_checked": len(groups)}


def g2_detail(cands: np.ndarray, pop: Population, rng: np.random.Generator, groups: int,
              cfg: GameConfig = DEFAULT_GAME, by_family: bool = True, family_groups: int = 20_000) -> list[dict]:
    field = G2Field.from_population(pop.allocs, rng, groups, cfg)
    ev = field.evaluate(cands)
    out = []
    fam_scores = {}
    if by_family:
        for f in np.unique(pop.labels):
            members = pop.allocs[pop.labels == f]
            if len(members) >= 3:
                fam_scores[f] = G2Field.from_population(members, rng, family_groups, cfg).mean_payout(cands)
    for i in range(len(cands)):
        out.append({"mean": float(ev["mean"][i]), "se": float(ev["se"][i]),
                    "ci95": [float(ev["mean"][i] - 1.96 * ev["se"][i]), float(ev["mean"][i] + 1.96 * ev["se"][i])],
                    "pos": ev["pos"][i].tolist(), "castle_points": float(ev["castle_points"][i]),
                    "castle_win": ev["castle_win"][i].tolist(), "castle_tie": ev["castle_tie"][i].tolist(),
                    "by_family": {f: float(s[i]) for f, s in fam_scores.items()}, "groups": groups})
    return out


def paired_comparison(field: G2Field, X: np.ndarray, ref: int = 0) -> list[dict]:
    """Paired (CRN) differences of each candidate vs candidate `ref` with 95% CIs."""
    P = field.payout_samples(X)
    d = P - P[ref]
    n = P.shape[1]
    out = []
    for i in range(len(X)):
        m = float(d[i].mean())
        se = float(d[i].std(ddof=1) / np.sqrt(n)) if i != ref else 0.0
        lo, hi = m - 1.96 * se, m + 1.96 * se
        verdict = "reference" if i == ref else ("worse" if hi < 0 else "better" if lo > 0 else "inconclusive")
        out.append({"diff": m, "se": se, "ci95": [lo, hi], "verdict": verdict})
    return out


# --------------------------------------------------------------------------
# robustness
# --------------------------------------------------------------------------

def robustness_summary(S: np.ndarray, scenario_names: list[str]) -> dict:
    """S: (candidates, scenarios) expected scores.  Equal-weight mean is the stated mixture."""
    mean = S.mean(1)
    worst = S.min(1)
    return {"mean": mean, "worst": worst, "worst_scenario": [scenario_names[j] for j in S.argmin(1)],
            "balanced": 0.5 * mean + 0.5 * worst,
            "cvar_2": np.sort(S, 1)[:, :2].mean(1)}


def weight_sensitivity(S: np.ndarray, rng: np.random.Generator, draws: int = 1000, alpha: float = 1.0) -> dict:
    """Linear sensitivity: random Dirichlet scenario weights; how often each candidate is best.

    Exact for Game 1 (scores are linear in the population mixture).  For Game 2
    use `g2_mixture_sensitivity`, which re-simulates mixed populations.
    """
    W = rng.dirichlet(np.full(S.shape[1], alpha), draws)
    scores = W @ S.T                                   # (draws, candidates)
    best = scores.argmax(1)
    ranks = (-scores).argsort(1).argsort(1)            # 0 = best
    return {"win_freq": np.bincount(best, minlength=S.shape[0]) / draws,
            "mean_rank": ranks.mean(0), "p10": np.percentile(scores, 10, 0),
            "p90": np.percentile(scores, 90, 0), "weights": W}


def g2_mixture_sensitivity(X: np.ndarray, pops: dict[str, Population], rng: np.random.Generator,
                           draws: int, groups: int, pop_size: int, cfg: GameConfig = DEFAULT_GAME,
                           alpha: float = 1.0) -> dict:
    names = list(pops)
    W = rng.dirichlet(np.full(len(names), alpha), draws)
    scores = np.empty((draws, len(X)))
    for d in range(draws):
        counts = rng.multinomial(pop_size, W[d])
        mixed = np.concatenate([pops[n].allocs[rng.integers(0, len(pops[n]), c)] for n, c in zip(names, counts) if c])
        scores[d] = G2Field.from_population(mixed, rng, groups, cfg).mean_payout(X)
    best = scores.argmax(1)
    ranks = (-scores).argsort(1).argsort(1)
    return {"win_freq": np.bincount(best, minlength=len(X)) / draws, "mean_rank": ranks.mean(0),
            "p10": np.percentile(scores, 10, 0), "p90": np.percentile(scores, 90, 0),
            "mean": scores.mean(0), "weights": W, "scenarios": names}


def g1_score_matrix(X: np.ndarray, pops: dict[str, Population], cfg: GameConfig = DEFAULT_GAME) -> np.ndarray:
    return np.stack([g1_scores(X, g1_tables(p.allocs, cfg)) for p in pops.values()], axis=1)


def g2_score_matrix(X: np.ndarray, pops: dict[str, Population], rng: np.random.Generator, groups: int,
                    cfg: GameConfig = DEFAULT_GAME) -> tuple[np.ndarray, np.ndarray]:
    """(means, standard errors), each (candidates, scenarios), using one CRN field per scenario."""
    M, SE = [], []
    for p in pops.values():
        ev = G2Field.from_population(p.allocs, rng, groups, cfg).evaluate(X)
        M.append(ev["mean"])
        SE.append(ev["se"])
    return np.stack(M, 1), np.stack(SE, 1)
