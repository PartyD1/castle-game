"""Strategic analysis (the 'why' questions) as explicit, controlled experiments.

Game 1 questions use exact constrained optima over all 4.6M allocations.
Game 2 questions use the screened candidate set evaluated on one CRN field
plus targeted re-simulation of the recommended allocation.
"""
from __future__ import annotations

import numpy as np

from .config import DEFAULT_GAME, GameConfig
from .generators import jitter
from .optimize.best_response import g1_best_response_dp
from .vectorized import G2Field, all_allocations, g1_scores, g1_tables


def _best_where(A, s, mask):
    if not mask.any():
        return None, float("nan")
    i = np.flatnonzero(mask)[np.argmax(s[mask])]
    return A[i].tolist(), float(s[i])


def g1_analysis(holdout: dict, pick: np.ndarray, cfg: GameConfig = DEFAULT_GAME) -> dict:
    A = all_allocations(cfg)
    nonzero = (A > 0).sum(1)
    out = {"castle1_sacrifice": {}, "n_targets": {}, "castle_prices": {}, "near_optimal": {},
           "proportional_predictability": {}, "artifact_check": {}}
    C = cfg.n_castles
    for name, pop in holdout.items():
        table = g1_tables(pop.allocs, cfg)
        s = g1_scores(A, table)
        best_all = _best_where(A, s, np.ones(len(A), bool))
        out["castle1_sacrifice"][name] = {"best_any": best_all, "best_c1_zero": _best_where(A, s, A[:, 0] == 0),
                                          "best_c1_positive": _best_where(A, s, A[:, 0] > 0)}
        out["n_targets"][name] = {int(k): _best_where(A, s, nonzero == k) for k in range(1, C + 1)}
        # price of each castle: soldiers needed to beat 50% / 80% of the population, and points per soldier
        q50 = np.percentile(pop.allocs, 50, axis=0)
        q80 = np.percentile(pop.allocs, 80, axis=0)
        mean = pop.allocs.mean(0)
        out["castle_prices"][name] = {
            "mean_soldiers": mean.tolist(), "share_of_soldiers": (mean / cfg.soldiers).tolist(),
            "share_of_value": (cfg.values_arr / cfg.total_points).tolist(),
            "soldiers_to_beat_50pct": (q50 + 1).tolist(), "soldiers_to_beat_80pct": (q80 + 1).tolist(),
            "points_per_soldier_80pct": (cfg.values_arr * 0.8 / (q80 + 1)).tolist(),
            # marginal value of the pick's last soldier on each castle (from the exact tables)
            "pick_marginal_value_of_one_more": [float(table[c, min(pick[c] + 1, cfg.soldiers)] - table[c, pick[c]])
                                                for c in range(C)],
        }
        near = s >= s.max() - 0.05
        Ns = A[near]
        out["near_optimal"][name] = {"count_within_0.05": int(near.sum()),
                                     "count_within_0.10": int((s >= s.max() - 0.10).sum()),
                                     "max_l1_from_best": int(np.abs(Ns - A[np.argmax(s)]).sum(1).max())}
        # does the pick depend on exact tie spikes? smooth the population with +-few soldier noise
        rng = np.random.default_rng(0)
        smooth = jitter(pop.allocs, rng, 4)
        t2 = g1_tables(smooth, cfg)
        br2, v2 = g1_best_response_dp(t2)
        out["artifact_check"][name] = {"pick_score": float(g1_scores(pick, table)[0]),
                                       "pick_score_smoothed_pop": float(g1_scores(pick, t2)[0]),
                                       "optimum": float(s.max()), "optimum_smoothed_pop": v2,
                                       "share_on_multiples_of_5": float(np.mean(pop.allocs % 5 == 0))}
    # predictability: how much a tailored counter extracts from each simple heuristic
    for nm, alloc in {"proportional": [7, 13, 20, 27, 33], "equal": [20] * 5, "linear_0_40": [0, 10, 20, 30, 40],
                      "pick": pick.tolist()}.items():
        _, v = g1_best_response_dp(g1_tables(np.array([alloc]), cfg))
        out["proportional_predictability"][nm] = {"alloc": alloc, "counter_score": v,
                                                  "victim_score": cfg.total_points - v}
    return out


def g2_analysis(screen: dict, holdout: dict, pick: np.ndarray, g1_pick: np.ndarray, rng: np.random.Generator,
                groups: int, cfg: GameConfig = DEFAULT_GAME) -> dict:
    X, m, cp = screen["allocs"], screen["mean"], screen["castle_points"]
    nz = (X > 0).sum(1)
    out = {}
    out["castle1_sacrifice"] = {"best_c1_zero": _best_where(X, m, X[:, 0] == 0),
                                "best_c1_positive": _best_where(X, m, X[:, 0] > 0),
                                "mean_top100_c1": float(X[np.argsort(-m)[:100], 0].mean())}
    out["n_targets"] = {int(k): _best_where(X, m, nz == k) for k in range(1, cfg.n_castles + 1)}
    top = np.argsort(-m)[:100]
    out["top100_mean_alloc"] = X[top].mean(0).tolist()
    out["top100_nonzero_castles"] = np.bincount(nz[top], minlength=cfg.n_castles + 1).tolist()
    # payout vs castle points: does maximizing points maximize payout?
    out["corr_points_payout"] = float(np.corrcoef(cp, m)[0, 1])
    out["best_by_points"] = {"alloc": X[np.argmax(cp)].tolist(), "points": float(cp.max()),
                             "payout": float(m[np.argmax(cp)])}
    out["best_by_payout"] = {"alloc": X[np.argmax(m)].tolist(), "points": float(cp[np.argmax(m)]),
                             "payout": float(m.max())}
    # G1 pick played in G2 and G2 pick, per scenario, with fresh groups
    rows = {}
    for name, pop in holdout.items():
        f = G2Field.from_population(pop.allocs, rng, groups, cfg)
        ev = f.evaluate(np.array([pick, g1_pick]))
        rows[name] = {"g2_pick": {"payout": float(ev["mean"][0]), "points": float(ev["castle_points"][0]),
                                  "pos": ev["pos"][0].tolist()},
                      "g1_pick": {"payout": float(ev["mean"][1]), "points": float(ev["castle_points"][1]),
                                  "pos": ev["pos"][1].tolist()}}
    out["g1_vs_g2_pick"] = rows
    return out
